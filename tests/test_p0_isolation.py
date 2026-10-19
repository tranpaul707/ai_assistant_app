"""Two-user HTTP isolation through real JWT validation, Redis Lua and Chroma.

Certificate transport, model inference and Google OAuth/Gmail are synthetic.
Checkpoints use LangGraph's in-memory saver; no live private data is accessed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from api.main import app
from api.routes import auth_gmail
from agents import agent, graph
from core import auth
from core.identity import owner_namespace
from knowledge import ingest as ingestion, retrieve as retrieval
from memory import history, long_term, threads
from memory.checkpointer import thread_config
from services.gmail import oauth_state, token_store


class LocalEmbeddings(Embeddings):
    """Deterministic vectors; exercise actual Chroma filtering without Ollama."""

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [1.0, float("alpha" in text.lower()), float("bravo" in text.lower())]


class PrivateEchoModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "synthetic-isolation"

    def bind_tools(self, tools, **kwargs):
        return self

    def _response(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and "document" in last.content:
            # A forged model-generated owner must not override injected context.
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_private_knowledge",
                        "id": "docs",
                        "args": {"query": "private document", "user_sub": "bravo"},
                    }
                ],
            )
        if isinstance(last, HumanMessage) and "mail" in last.content:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_email",
                        "id": "email",
                        "args": {"message_id": last.content.split()[-1], "user_sub": "bravo"},
                    }
                ],
            )
        if isinstance(last, ToolMessage):
            if last.name == "read_email":
                result = json.loads(last.content)
                return AIMessage(
                    content=result["message"]["body"]
                    if result["status"] == "ok"
                    else result["code"]
                )
            return AIMessage(content=last.content)
        private_memory = [
            str(m.content)
            for m in messages
            if isinstance(m, SystemMessage) and m.content != agent.SYSTEM_PROMPT
        ]
        return AIMessage(content=str(last.content) + " " + " ".join(private_memory))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        response = self._response(messages)
        yield ChatGenerationChunk(
            message=AIMessageChunk(content=response.content, tool_calls=response.tool_calls)
        )


@pytest.fixture(scope="module")
def signing_material():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return crypt.RSASigner.from_string(pem, key_id="fixture"), public.decode()


@pytest.fixture
def tokens(monkeypatch, signing_material):
    signer, public = signing_material
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "synthetic-client")
    # Keep Google's real signature/audience/issuer/expiry verification.
    certificate_response = SimpleNamespace(
        status=200, data=json.dumps({"fixture": public}).encode()
    )
    monkeypatch.setattr(
        auth.google_requests, "Request", lambda: lambda *args, **kwargs: certificate_response
    )

    def make(sub="alpha", **overrides):
        now = int(time.time())
        payload = {
            "sub": sub,
            "iat": now - 10,
            "exp": now + 600,
            "aud": "synthetic-client",
            "iss": "https://accounts.google.com",
        }
        payload.update(overrides)
        return jwt.encode(signer, payload).decode()

    return make


@pytest.fixture
def disposable_redis(monkeypatch):
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.fail("P0 API tests require redis-server (see backend testing instructions)")
    # A private Unix socket and no TCP port avoid existing Redis instances entirely.
    with tempfile.TemporaryDirectory(prefix="p0-", dir="/tmp") as directory:
        socket = str(Path(directory) / "redis.sock")
        process = subprocess.Popen(
            [
                executable,
                "--port",
                "0",
                "--unixsocket",
                socket,
                "--unixsocketperm",
                "700",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                directory,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        connection = redis.Redis(
            unix_socket_path=socket,
            decode_responses=True,
            retry=Retry(NoBackoff(), 0),
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        try:
            for _ in range(100):
                try:
                    connection.ping()
                    break
                except redis.RedisError:
                    time.sleep(0.02)
            else:
                pytest.fail("Disposable Redis did not start")
            for module in (threads, long_term, oauth_state):
                monkeypatch.setattr(module, "_client", lambda: connection)
            yield connection
        finally:
            connection.close()
            process.terminate()
            process.wait(timeout=5)


@pytest.fixture
def environment(monkeypatch, tmp_path, disposable_redis, tokens):
    from api.routes import upload

    store = Chroma(
        collection_name="p0_isolation",
        embedding_function=LocalEmbeddings(),
        persist_directory=str(tmp_path / "chroma"),
    )
    monkeypatch.setattr(ingestion, "vector_store", store)
    monkeypatch.setattr(retrieval, "vector_store", store)
    monkeypatch.setattr(upload, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(token_store, "OAUTH_DIR", tmp_path / "oauth")
    monkeypatch.setattr(token_store, "GMAIL_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    saver = InMemorySaver()
    monkeypatch.setattr(graph, "get_checkpointer", lambda: saver)
    monkeypatch.setattr(history, "get_checkpointer", lambda: saver)
    monkeypatch.setattr(agent, "llm", PrivateEchoModel())
    monkeypatch.setattr(
        graph,
        "classify",
        lambda query, **kwargs: "private"
        if any(word in query for word in ("document", "mail"))
        else "general",
    )
    # Memory reads remain real; model-based extraction is excluded from these fixtures.
    monkeypatch.setattr(graph.memory_manager, "ingest_turn", lambda *args, **kwargs: None)
    graph.get_graph.cache_clear()
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                store=store,
                redis=disposable_redis,
                tokens=tokens,
                saver=saver,
                directory=tmp_path,
            )
    finally:
        graph.get_graph.cache_clear()


def headers(env, owner):
    return {"Authorization": f"Bearer {env.tokens(owner)}"}


def turn(env, owner, thread_id, message="hello"):
    return env.client.post(
        "/chat", headers=headers(env, owner), json={"message": message, "thread_id": thread_id}
    )


@pytest.mark.parametrize(
    "method,path,arguments",
    [
        ("get", "/threads", {}),
        ("get", f"/threads/{uuid4()}", {}),
        ("post", "/chat", {"json": {"message": "private", "thread_id": str(uuid4())}}),
        ("post", "/upload", {"files": {"file": ("same.txt", b"private")}}),
        ("get", "/auth/gmail/status", {}),
        ("post", "/auth/gmail/start", {}),
    ],
)
def test_all_private_routes_require_authentication(environment, method, path, arguments):
    env = environment
    for authorization in (None, "Bearer forged.token.signature", "Basic alpha", "Bearer"):
        response = env.client.request(
            method,
            path,
            headers={"Authorization": authorization} if authorization else {},
            **arguments,
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication required"}
        assert response.headers["www-authenticate"] == "Bearer"
    assert list(env.redis.scan_iter()) == []
    assert not (env.directory / "uploads").exists()


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "wrong"},
        {"iss": "https://attacker.example"},
        {"exp": 1},
        {"iat": 4102444800},
        {"sub": None},
        {"sub": ["alpha"]},
        {"sub": "../alpha"},
        {"exp": "4102444800"},
        {"exp": True},
    ],
)
def test_signed_invalid_claims_are_rejected_before_private_access(environment, claims):
    response = environment.client.get(
        "/threads", headers={"Authorization": f"Bearer {environment.tokens(**claims)}"}
    )
    assert response.status_code == 401
    assert list(environment.redis.scan_iter()) == []


def test_unsigned_payload_and_non_object_claims_never_authenticate(environment, signing_material):
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"sub": "alpha"}).encode()).decode().rstrip("=")
    for token in (f"e30.{payload}.", jwt.encode(signing_material[0], ["alpha"]).decode()):
        assert (
            environment.client.get(
                "/threads", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )


def test_threads_history_checkpoints_and_memory_are_private(environment):
    env = environment
    alpha, bravo = str(uuid4()), str(uuid4())
    long_term.persist_items(
        "alpha", [long_term.new_item(memory_type="fact", key="code", text="PRIVATE_ALPHA_MEMORY")]
    )
    long_term.persist_items(
        "bravo", [long_term.new_item(memory_type="fact", key="code", text="PRIVATE_BRAVO_MEMORY")]
    )
    assert "PRIVATE_ALPHA_MEMORY" in turn(env, "alpha", alpha, "remember").text
    bravo_response = turn(env, "bravo", bravo, "remember")
    assert "PRIVATE_BRAVO_MEMORY" in bravo_response.text
    assert "PRIVATE_ALPHA_MEMORY" not in bravo_response.text
    for owner, thread in (("alpha", alpha), ("bravo", bravo)):
        listing = env.client.get("/threads", headers=headers(env, owner)).json()["threads"]
        assert [row["thread_id"] for row in listing] == [thread]
        response = env.client.get(f"/threads/{thread}", headers=headers(env, owner))
        assert response.status_code == 200 and response.json()["messages"]
    before = env.saver.get_tuple(thread_config(alpha, user_sub="alpha"))
    assert env.client.get(f"/threads/{alpha}", headers=headers(env, "bravo")).status_code == 404
    assert turn(env, "bravo", alpha, "steal").status_code == 404
    assert env.saver.get_tuple(thread_config(alpha, user_sub="alpha")) == before
    assert env.saver.get_tuple(thread_config(alpha, user_sub="bravo")) is None
    assert not env.redis.exists("chat_threads:local")
    assert threads.get_thread_meta(alpha, user_sub="alpha")["user_sub"] == "alpha"


def test_unowned_legacy_and_damaged_registry_never_expose_checkpoints(environment):
    env = environment
    legacy = str(uuid4())
    env.redis.set(
        f"chat_thread_meta:{legacy}", json.dumps({"thread_id": legacy, "title": "legacy"})
    )
    assert env.client.get(f"/threads/{legacy}", headers=headers(env, "alpha")).status_code == 404
    assert turn(env, "alpha", legacy).status_code == 404
    owned = str(uuid4())
    assert turn(env, "alpha", owned).status_code == 200
    env.redis.delete(threads._meta_key(owned, "alpha"))
    assert env.client.get(f"/threads/{owned}", headers=headers(env, "alpha")).status_code == 404
    assert turn(env, "alpha", owned).status_code == 404
    # A checkpoint is never enough to grant access without ownership metadata.
    with pytest.raises(PermissionError):
        history.messages_for_thread(owned, user_sub="alpha")


@pytest.mark.parametrize("thread", ["user123", "../../other", "x:y", "", "A" * 200])
def test_invalid_thread_ids_never_reach_storage(environment, thread):
    assert turn(environment, "alpha", thread).status_code == 422
    assert list(environment.redis.scan_iter()) == []


def test_atomic_creation_allows_only_one_owner(environment):
    thread = str(uuid4())

    def create(owner):
        try:
            return threads.upsert_thread(thread, user_sub=owner)["user_sub"]
        except PermissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ["alpha", "bravo"]))
    winners = [owner for owner in results if owner]
    assert len(winners) == 1
    assert threads.list_threads(winners[0])[0]["user_sub"] == winners[0]
    assert threads.list_threads("bravo" if winners[0] == "alpha" else "alpha") == []


def test_same_named_uploads_and_model_selected_owner_are_isolated(environment):
    env = environment
    responses = []
    for owner, body in (
        ("alpha", b"PRIVATE_ALPHA_DOCUMENT"),
        ("bravo", b"PRIVATE_BRAVO_DOCUMENT"),
        ("alpha", b"SECOND_ALPHA_DOCUMENT"),
    ):
        response = env.client.post(
            "/upload", headers=headers(env, owner), files={"file": ("../../same.txt", body)}
        )
        assert response.status_code == 200
        responses.append(response.json())
    assert len({row["document_id"] for row in responses}) == 3
    assert all(row["filename"] == "same.txt" for row in responses)
    assert (
        len(list((env.directory / "uploads" / "v2" / owner_namespace("alpha")).glob("*.txt"))) == 2
    )
    alpha = turn(env, "alpha", str(uuid4()), "find my document").text
    bravo = turn(env, "bravo", str(uuid4()), "find my document").text
    assert "PRIVATE_ALPHA_DOCUMENT" in alpha and "SECOND_ALPHA_DOCUMENT" in alpha
    assert "PRIVATE_BRAVO_DOCUMENT" not in alpha
    assert "PRIVATE_BRAVO_DOCUMENT" in bravo and "PRIVATE_ALPHA_DOCUMENT" not in bravo
    assert "SECOND_ALPHA_DOCUMENT" not in bravo


def test_archival_replacement_and_deletion_stay_owner_scoped(environment):
    env = environment
    for owner in ("alpha", "bravo"):
        ingestion.ingest(
            [Document(page_content=f"{owner} first", metadata={"user_sub": "attacker"})],
            "email:identical",
            user_sub=owner,
        )
    bravo_before = env.store.get(where={"user_sub": "bravo"})
    ingestion.ingest([Document(page_content="alpha updated")], "email:identical", user_sub="alpha")
    assert env.store.get(where={"user_sub": "bravo"}) == bravo_before
    alpha = env.store.get(where={"user_sub": "alpha"})
    assert alpha["documents"] == ["alpha updated"]
    assert set(alpha["ids"]).isdisjoint(bravo_before["ids"])
    assert retrieval.retrieve("first", user_sub="alpha") == []  # archived mail is excluded
    for operation in (
        lambda: retrieval.retrieve("first", user_sub=""),
        lambda: ingestion.ingest([], "same", user_sub=""),
    ):
        with pytest.raises(ValueError):
            operation()


def test_owner_is_injected_and_absent_from_model_visible_schema():
    from tools.rag import search_private_knowledge
    from tools.gmail import search_gmail, read_email, read_email_thread

    for tool in (search_private_knowledge, search_gmail, read_email, read_email_thread):
        properties = tool.tool_call_schema.model_json_schema()["properties"]
        assert "user_sub" not in properties and "config" not in properties
    assert "Sign in" in search_private_knowledge.invoke({"query": "private"}, config={})


@pytest.fixture
def oauth_flow(environment, monkeypatch):
    def url(*, state, **kwargs):
        return (
            f"https://accounts.google.com/o/oauth2/auth?state={state}&code_challenge=synthetic",
            "v" * 64,
        )

    monkeypatch.setattr(auth_gmail, "authorization_url", url)
    exchanged = []

    def exchange(code, *, state, code_verifier):
        exchanged.append((code, state, code_verifier))
        assert code_verifier == "v" * 64
        return SimpleNamespace(
            id_token=environment.tokens("alpha"),
            token="alpha-access",
            refresh_token="alpha-refresh",
            scopes=["openid"],
            expiry=None,
        )

    monkeypatch.setattr(auth_gmail, "exchange_code", exchange)
    return exchanged


def initiate(env, owner="alpha"):
    from urllib.parse import parse_qs, urlparse

    response = env.client.post("/auth/gmail/start", headers=headers(env, owner))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    url = response.json()["authorization_url"]
    assert "id_token" not in url and "Bearer" not in url
    state = parse_qs(urlparse(url).query)["state"][0]
    assert 0 < env.redis.ttl(oauth_state._key(state)) <= 600
    return state


def callback(env, state, **kwargs):
    return env.client.get(
        "/auth/gmail/callback",
        params={"state": state, "code": "synthetic-code", **kwargs},
        follow_redirects=False,
    )


def test_oauth_success_is_account_bound_single_use_and_encrypted(environment, oauth_flow):
    env = environment
    state = initiate(env)
    response = callback(env, state)
    assert response.status_code == 307 and "gmail=connected" in response.headers["location"]
    assert token_store.load_tokens("alpha")["refresh_token"] == "alpha-refresh"
    assert token_store.load_tokens("bravo") is None
    assert env.client.get("/auth/gmail/status", headers=headers(env, "alpha")).json()["connected"]
    assert not env.client.get("/auth/gmail/status", headers=headers(env, "bravo")).json()[
        "connected"
    ]
    encrypted = token_store._path_for("alpha").read_bytes()
    assert b"alpha-refresh" not in encrypted and b"alpha-access" not in encrypted
    assert token_store._path_for("alpha").stat().st_mode & 0o777 == 0o600
    assert token_store._path_for("alpha").parent.stat().st_mode & 0o777 == 0o700
    assert callback(env, state).status_code == 400
    assert len(oauth_flow) == 1


@pytest.mark.parametrize(
    "kind",
    ["missing", "unknown", "expired", "browser_mismatch", "missing_browser", "unknown_error"],
)
def test_oauth_rejects_bad_state_before_exchange(environment, oauth_flow, kind):
    env = environment
    state = initiate(env)
    if kind in {"unknown", "unknown_error"}:
        state = "x" * 43
    elif kind == "expired":
        env.redis.pexpire(oauth_state._key(state), 1)
        time.sleep(0.02)
    elif kind == "browser_mismatch":
        env.client.cookies.set(
            auth_gmail._BROWSER_COOKIE, "wrong", domain="testserver.local", path="/auth/gmail"
        )
    elif kind == "missing_browser":
        env.client.cookies.clear()
    elif kind == "missing":
        state = ""
    response = callback(
        env, state, **({"error": "access_denied"} if kind == "unknown_error" else {})
    )
    assert response.status_code == 400
    assert oauth_flow == []
    assert token_store.load_tokens("alpha") is None


def test_oauth_account_mismatch_preserves_both_users_credentials(
    environment, oauth_flow, monkeypatch
):
    env = environment
    for owner in ("alpha", "bravo"):
        token_store.save_tokens(owner, {"refresh_token": f"existing-{owner}"})
    state = initiate(env)
    monkeypatch.setattr(
        auth_gmail,
        "exchange_code",
        lambda *args, **kwargs: SimpleNamespace(
            id_token=env.tokens("bravo"), token="bravo-access", refresh_token="bravo-refresh"
        ),
    )
    response = callback(env, state)
    assert "account_mismatch" in response.headers["location"]
    assert token_store.load_tokens("alpha") == {"refresh_token": "existing-alpha"}
    assert token_store.load_tokens("bravo") == {"refresh_token": "existing-bravo"}
    assert callback(env, state).status_code == 400


def test_invalid_oauth_identity_does_not_fall_back_to_userinfo(
    environment, oauth_flow, monkeypatch
):
    state = initiate(environment)
    monkeypatch.setattr(
        auth_gmail,
        "exchange_code",
        lambda *args, **kwargs: SimpleNamespace(
            id_token="forged.invalid.signature", token="synthetic", refresh_token="synthetic"
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid ID token triggered userinfo fallback")

    monkeypatch.setattr(auth_gmail.requests, "get", forbidden)
    assert "unverified_account" in callback(environment, state).headers["location"]
    assert token_store.load_tokens("alpha") is None


def test_verified_userinfo_identity_must_match_initiator(environment, oauth_flow, monkeypatch):
    state = initiate(environment)
    monkeypatch.setattr(
        auth_gmail,
        "exchange_code",
        lambda *args, **kwargs: SimpleNamespace(
            id_token=None, token="synthetic", refresh_token="synthetic"
        ),
    )

    class Userinfo:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sub": "bravo"}

    def userinfo(url, **kwargs):
        assert url == "https://www.googleapis.com/oauth2/v3/userinfo"
        assert kwargs["headers"] == {"Authorization": "Bearer synthetic"}
        assert kwargs["timeout"] == 15
        return Userinfo()

    monkeypatch.setattr(auth_gmail.requests, "get", userinfo)
    assert "account_mismatch" in callback(environment, state).headers["location"]
    assert token_store.load_tokens("alpha") is None


def test_cancelled_oauth_state_is_consumed_and_error_text_is_not_reflected(environment, oauth_flow):
    state = initiate(environment)
    response = callback(environment, state, error="SENSITIVE_PROVIDER_ERROR")
    assert "authorization_denied" in response.headers["location"]
    assert "SENSITIVE_PROVIDER_ERROR" not in response.headers["location"]
    assert callback(environment, state).status_code == 400 and oauth_flow == []


def test_concurrent_oauth_consumption_has_only_one_winner(environment, oauth_flow):
    state = initiate(environment)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(oauth_state.consume_state, [state, state]))
    assert sum(result is not None for result in results) == 1


def test_old_token_url_start_is_disabled(environment):
    response = environment.client.get(
        "/auth/gmail/start", params={"id_token": environment.tokens()}, follow_redirects=False
    )
    assert response.status_code == 405
    assert (
        environment.client.post(
            "/auth/gmail/start", params={"id_token": environment.tokens()}
        ).status_code
        == 401
    )


def test_missing_encryption_key_fails_before_oauth_grant(environment, oauth_flow, monkeypatch):
    monkeypatch.setattr(token_store, "GMAIL_TOKEN_ENCRYPTION_KEY", "")
    assert (
        environment.client.post(
            "/auth/gmail/start", headers=headers(environment, "alpha")
        ).status_code
        == 503
    )
    assert list(environment.redis.scan_iter()) == []
    assert oauth_flow == []
    with pytest.raises(RuntimeError):
        token_store.save_tokens("alpha", {"refresh_token": "private"})
    assert not token_store._path_for("alpha").exists()


def test_credentials_cannot_be_transplanted_or_loaded_from_legacy_plaintext(environment):
    env = environment
    token_store.OAUTH_DIR.mkdir()
    (token_store.OAUTH_DIR / "alpha.json").write_text(
        json.dumps({"refresh_token": "legacy-private"})
    )
    assert token_store.load_tokens("alpha") is None
    token_store.save_tokens("alpha", {"refresh_token": "alpha-private"})
    token_store._path_for("bravo").write_bytes(token_store._path_for("alpha").read_bytes())
    assert token_store.load_tokens("bravo") is None
    assert token_store.load_tokens("alpha") == {"refresh_token": "alpha-private"}


def test_failed_atomic_credential_update_preserves_previous_file(environment, monkeypatch, caplog):
    token_store.save_tokens("alpha", {"refresh_token": "first-private"})
    original = token_store._path_for("alpha").read_bytes()

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(token_store.os, "replace", fail)
    with pytest.raises(OSError):
        token_store.save_tokens("alpha", {"refresh_token": "next-private"})
    assert token_store._path_for("alpha").read_bytes() == original
    assert not list(token_store._path_for("alpha").parent.glob(".credential-*"))
    assert "first-private" not in caplog.text and "next-private" not in caplog.text


def test_pkce_url_and_exchange_use_same_state_and_verifier(monkeypatch):
    from services.gmail import client
    from unittest.mock import Mock
    from urllib.parse import parse_qs, urlparse
    import base64
    import hashlib

    monkeypatch.setattr(client, "GOOGLE_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(client, "GOOGLE_CLIENT_SECRET", "synthetic-secret")
    url, verifier = client.authorization_url(state="s" * 43)
    params = parse_qs(urlparse(url).query)
    assert params["state"] == ["s" * 43]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    ]
    assert "synthetic-secret" not in url
    flow = Mock()
    from google.oauth2.credentials import Credentials

    flow.credentials = Credentials(token="synthetic-access")
    factory = Mock(return_value=flow)
    monkeypatch.setattr(client, "_flow", factory)
    client.exchange_code("synthetic-code", state="s" * 43, code_verifier=verifier)
    factory.assert_called_once_with(state="s" * 43, code_verifier=verifier)
    flow.fetch_token.assert_called_once_with(code="synthetic-code")


def test_oauth_query_redaction_preserves_route_input_but_hides_access_log_secrets():
    import asyncio
    from api.privacy import RedactOAuthQuery

    scope = {
        "type": "http",
        "path": "/auth/gmail/callback",
        "query_string": b"code=secret&state=secret",
    }
    seen = []

    async def application(scope, receive, send):
        assert scope["query_string"] == b"code=secret&state=secret"
        await send({"type": "http.response.start", "status": 400, "headers": []})

    async def send(message):
        seen.append(scope["query_string"])

    async def receive():
        return {"type": "http.request"}

    asyncio.run(RedactOAuthQuery(application)(scope, receive, send))
    assert seen == [b""]


def test_gmail_http_turns_use_only_the_callers_encrypted_mailbox_credentials(
    environment, monkeypatch
):
    from datetime import datetime, timedelta
    from services.gmail import client
    from googleapiclient.errors import HttpError
    import base64
    import httplib2

    env = environment
    accesses = []
    for owner in ("alpha", "bravo"):
        token_store.save_tokens(
            owner,
            {
                "token": f"{owner}-access",
                "refresh_token": f"{owner}-refresh",
                "expiry": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            },
        )

    class Mailbox:
        def __init__(self, owner):
            self.owner = owner

        def users(self):
            return self

        def messages(self):
            return self

        def get(self, *, userId, id, format):
            assert userId == "me" and format == "full"
            accesses.append((self.owner, id))
            if id != f"{self.owner}-message":
                raise HttpError(httplib2.Response({"status": "404"}), b"not found")
            return SimpleNamespace(
                execute=lambda **kwargs: {
                    "id": id,
                    "threadId": f"{self.owner}-thread",
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                f"PRIVATE_{self.owner.upper()}_MAIL".encode()
                            ).decode()
                        },
                    },
                }
            )

    def build(api, version, *, http, **kwargs):
        assert api == "gmail" and version == "v1"
        # Credential loading/decryption/selection remain application code.
        owner = http.credentials.token.removesuffix("-access")
        assert owner in {"alpha", "bravo"}
        return Mailbox(owner)

    monkeypatch.setattr(client, "build", build)
    alpha = turn(env, "alpha", str(uuid4()), "mail alpha-message").text
    assert "PRIVATE_ALPHA_MAIL" in alpha and "PRIVATE_BRAVO_MAIL" not in alpha
    bravo = turn(env, "bravo", str(uuid4()), "mail bravo-message").text
    assert "PRIVATE_BRAVO_MAIL" in bravo and "PRIVATE_ALPHA_MAIL" not in bravo
    guessed = turn(env, "alpha", str(uuid4()), "mail bravo-message").text
    assert "PRIVATE_BRAVO_MAIL" not in guessed and "not_found" in guessed
    assert accesses == [
        ("alpha", "alpha-message"),
        ("bravo", "bravo-message"),
        ("alpha", "bravo-message"),
    ]


def test_oauth_exchange_failures_never_log_credentials(
    environment, oauth_flow, monkeypatch, caplog
):
    state = initiate(environment)

    def fail(*args, **kwargs):
        raise RuntimeError("SENSITIVE_REFRESH_TOKEN_AND_CODE")

    monkeypatch.setattr(auth_gmail, "exchange_code", fail)
    response = callback(environment, state)
    assert "token_exchange_failed" in response.headers["location"]
    assert "SENSITIVE_REFRESH_TOKEN_AND_CODE" not in caplog.text
    assert "SENSITIVE_REFRESH_TOKEN_AND_CODE" not in response.text


def test_missing_oauth_code_consumes_state_before_any_exchange(environment, oauth_flow):
    state = initiate(environment)
    response = environment.client.get(
        "/auth/gmail/callback", params={"state": state}, follow_redirects=False
    )
    assert response.status_code == 400
    assert callback(environment, state).status_code == 400
    assert oauth_flow == []


def test_oauth_reconnect_preserves_only_matching_owners_refresh_token(
    environment, oauth_flow, monkeypatch
):
    from google.oauth2.credentials import Credentials

    env = environment
    token_store.save_tokens("alpha", {"refresh_token": "original-alpha-refresh"})
    token_store.save_tokens("bravo", {"refresh_token": "original-bravo-refresh"})
    state = initiate(env)
    creds = Credentials(token="new-alpha-access", refresh_token=None, id_token=env.tokens("alpha"))
    monkeypatch.setattr(auth_gmail, "exchange_code", lambda *args, **kwargs: creds)
    response = callback(env, state)
    assert "gmail=connected" in response.headers["location"]
    assert token_store.load_tokens("alpha")["refresh_token"] == "original-alpha-refresh"
    assert token_store.load_tokens("alpha")["token"] == "new-alpha-access"
    assert token_store.load_tokens("bravo")["refresh_token"] == "original-bravo-refresh"
    assert creds.refresh_token is None


@pytest.mark.parametrize("damage", ["missing_owner", "missing_pkce", "short_pkce", "invalid_json"])
def test_malformed_redis_oauth_state_is_rejected_before_exchange(environment, oauth_flow, damage):
    state = initiate(environment)
    key = oauth_state._key(state)
    raw = json.loads(environment.redis.get(key))
    if damage == "missing_owner":
        raw.pop("sub")
    elif damage == "missing_pkce":
        raw.pop("code_verifier")
    elif damage == "short_pkce":
        raw["code_verifier"] = "short"
    environment.redis.set(key, "[invalid" if damage == "invalid_json" else json.dumps(raw))
    assert callback(environment, state).status_code == 400
    assert oauth_flow == [] and not environment.redis.exists(key)
