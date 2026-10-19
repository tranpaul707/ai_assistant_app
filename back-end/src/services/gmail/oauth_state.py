"""Expiring, single-use OAuth state shared by backend workers through Redis."""

import json
import re
from hashlib import sha256

import redis

from core.identity import require_identity
from core.settings import OAUTH_STATE_TTL_SECONDS, REDIS_URI


def _client() -> redis.Redis:
    return redis.from_url(REDIS_URI, decode_responses=True)


def _key(state: str) -> str:
    if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
        raise ValueError("Invalid OAuth state")
    return f"oauth:v2:state:{sha256(state.encode()).hexdigest()}"


def save_state(state: str, *, user_sub: str, code_verifier: str, browser_nonce: str) -> None:
    record = {
        "sub": require_identity(user_sub),
        "code_verifier": code_verifier,
        "browser_hash": sha256(browser_nonce.encode()).hexdigest(),
    }
    if not _client().set(_key(state), json.dumps(record), nx=True, ex=OAUTH_STATE_TTL_SECONDS):
        raise RuntimeError("OAuth state could not be created")


def consume_state(state: str) -> dict[str, str] | None:
    try:
        key = _key(state)
    except ValueError:
        return None
    raw = _client().getdel(key)
    if not isinstance(raw, (str, bytes)) or not raw:
        return None
    try:
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        require_identity(record.get("sub"))
        if not all(
            isinstance(record.get(key), str) and record[key]
            for key in ("code_verifier", "browser_hash")
        ):
            return None
        if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", record["code_verifier"]):
            return None
        if not re.fullmatch(r"[a-f0-9]{64}", record["browser_hash"]):
            return None
        return record
    except (ValueError, TypeError):
        return None
