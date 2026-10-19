"""Synthetic Gmail regressions: API boundaries, constraints, parsing and agent tools."""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError
from langchain_core.messages import AIMessage, HumanMessage

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from services.gmail import client
from services.gmail.models import Email, EmailSummary, SearchPage, email_data
from services.gmail.query import (
    broaden_gmail_queries,
    build_gmail_query,
    calendar_window,
    email_matches_people,
    extract_keywords,
    format_person_operator,
)
from services.gmail.to_documents import email_to_documents
from tools.gmail import read_email, read_email_thread, search_gmail

CONFIG = {"configurable": {"user_sub": "test-user"}}


def message(message_id="m1", *, sender="John <john@example.com>", timestamp=1000, body="Hello"):
    return {
        "id": message_id,
        "threadId": "thread1",
        "internalDate": str(timestamp),
        "labelIds": ["INBOX"],
        "snippet": "Preview only",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": '"Doe, Jane" <jane@example.com>'},
                {"name": "Subject", "value": "Interview response"},
                {"name": "Date", "value": "Tue, 2 Jan 2024 10:00:00 +0000"},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


def error(status=404):
    return HttpError(httplib2.Response({"status": str(status)}), b'{"error":"private detail"}')


def test_search_fetches_metadata_not_bodies_and_sorts_internal_date():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {"messages": [{"id": "old"}, {"id": "new"}]}
    messages.get.return_value.execute.side_effect = [message("old"), message("new", timestamp=2000)]
    with patch.object(client, "_service", return_value=service):
        page = client.search_emails("test-user", "internship", max_results=2)
    assert [email.id for email in page.messages] == ["new", "old"]
    assert page.messages[0].received_at == datetime.fromtimestamp(2, timezone.utc)
    assert all(call.kwargs["format"] == "metadata" for call in messages.get.call_args_list)
    assert all("snippet" in call.kwargs["fields"] for call in messages.get.call_args_list)
    assert "Subject" in messages.get.call_args.kwargs["metadataHeaders"]
    assert "body" not in email_data(page.messages[0])
    messages.list.return_value.execute.assert_called_with(num_retries=1)


def test_search_refills_after_zero_match_people_filter_without_full_reads():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.side_effect = [
        {"messages": [{"id": "wrong"}], "nextPageToken": "next"},
        {"messages": [{"id": "right"}]},
    ]
    messages.get.return_value.execute.side_effect = [
        message("wrong", sender="Johnson <johnson@newsletter.example>"),
        message("right"),
    ]
    with patch.object(client, "_service", return_value=service):
        page = client.search_emails(
            "test-user", "from:John newer_than:7d", max_results=1, sender_filter="John"
        )
    assert [email.id for email in page.messages] == ["right"]
    assert messages.list.call_args.kwargs["pageToken"] == "next"
    assert all(
        call.kwargs["q"] == "from:John newer_than:7d" for call in messages.list.call_args_list
    )
    assert page.scanned_count == 2 and page.pages_fetched == 2


def test_zero_matches_returns_no_unrelated_candidates():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {"messages": [{"id": "wrong"}]}
    messages.get.return_value.execute.return_value = message(
        "wrong", sender="Other <other@example.com>"
    )
    with patch.object(client, "_service", return_value=service):
        assert client.search_emails("test-user", "from:John", sender_filter="John").messages == []


def test_search_preserves_partial_results_and_continuation():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {
        "messages": [{"id": "gone"}, {"id": "live"}],
        "nextPageToken": "next",
    }
    messages.get.return_value.execute.side_effect = [error(), message("live")]
    with patch.object(client, "_service", return_value=service):
        page = client.search_emails("test-user", "interview", max_results=1)
    assert [email.id for email in page.messages] == ["live"]
    assert page.next_page_token == "next"
    assert page.errors == [{"id": "gone", "code": "not_found"}]


def test_search_pagination_is_bounded_even_when_nothing_matches():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.side_effect = [
        {"messages": [{"id": f"m{i}"}], "nextPageToken": f"p{i}"} for i in range(client.MAX_PAGES)
    ]
    messages.get.return_value.execute.return_value = message(sender="Other <other@example.com>")
    with patch.object(client, "_service", return_value=service):
        page = client.search_emails("test-user", "from:John", max_results=1, sender_filter="John")
    assert page.pages_fetched == client.MAX_PAGES
    assert page.next_page_token is not None
    assert page.messages == []


def test_later_page_failure_keeps_evidence_and_retry_token():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.side_effect = [
        {"messages": [{"id": "live"}], "nextPageToken": "next"},
        TimeoutError(),
    ]
    messages.get.return_value.execute.return_value = message("live")
    with patch.object(client, "_service", return_value=service):
        page = client.search_emails("test-user", "interview", max_results=2)
    assert len(page.messages) == 1
    assert page.errors == [{"id": "", "code": "api_error"}]
    assert page.next_page_token == "next"


def test_read_only_selected_message_and_bound_body():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = message("chosen", body="x" * 7000)
    with patch.object(client, "_service", return_value=service):
        email = client.read_email("test-user", "chosen")
    messages.get.assert_called_once_with(userId="me", id="chosen", format="full")
    messages.list.assert_not_called()
    assert len(email.body) == client.MAX_BODY_CHARS and email.body_truncated


def test_thread_fetches_metadata_then_latest_selected_bodies_chronologically():
    service = MagicMock()
    threads = service.users.return_value.threads.return_value
    messages = service.users.return_value.messages.return_value
    threads.get.return_value.execute.return_value = {
        "id": "thread1",
        "messages": [
            message("new", timestamp=3000),
            message("old", timestamp=1000),
            message("middle", timestamp=2000),
        ],
    }
    messages.get.return_value.execute.side_effect = [
        message("middle", timestamp=2000),
        message("new", timestamp=3000),
    ]
    with patch.object(client, "_service", return_value=service):
        thread = client.read_email_thread("test-user", "thread1", max_messages=2)
    assert threads.get.call_args.kwargs["format"] == "metadata"
    assert [call.kwargs["id"] for call in messages.get.call_args_list] == ["middle", "new"]
    assert [email.id for email in thread.messages] == ["middle", "new"]
    assert thread.total_messages == 3 and thread.truncated


def test_thread_keeps_other_messages_if_one_is_deleted():
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "id": "thread1",
        "messages": [message("gone"), message("live", timestamp=2000)],
    }
    service.users.return_value.messages.return_value.get.return_value.execute.side_effect = [
        error(),
        message("live"),
    ]
    with patch.object(client, "_service", return_value=service):
        thread = client.read_email_thread("test-user", "thread1")
    assert [email.id for email in thread.messages] == ["live"]
    assert thread.errors == [{"id": "gone", "code": "not_found"}]


def test_extract_body_prefers_plain_and_skips_text_attachment():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "text/plain",
                "filename": "private.txt",
                "body": {"data": base64.urlsafe_b64encode(b"attachment").decode()},
            },
            {
                "mimeType": "text/html",
                "body": {"data": base64.urlsafe_b64encode(b"<p>HTML &amp; text</p>").decode()},
            },
            {
                "mimeType": "text/plain",
                "body": {"data": base64.urlsafe_b64encode(b"Body text").decode()},
            },
        ],
    }
    assert client.extract_body(payload) == "Body text"
    payload["parts"].pop()
    assert client.extract_body(payload) == "HTML & text"
    assert (
        client._message_to_email({"id": "x", "payload": payload}).attachments[0].filename
        == "private.txt"
    )


def test_quoted_recipient_names_and_timestamp_fallback():
    raw = message()
    raw["internalDate"] = "invalid"
    summary = client._message_to_summary(raw)
    assert summary.recipients == ['"Doe, Jane" <jane@example.com>']
    assert summary.received_at == datetime(2024, 1, 2, 10, tzinfo=timezone.utc)
    assert summary.date_header.startswith("Tue") and summary.internal_date_ms is None


@pytest.mark.parametrize(
    "person,header,expected",
    [
        ("John", "Johnson <johnson@newsletter.example>", False),
        ("John", "John Smith <recruiter@example.com>", True),
        ('"John Smith"', "John Smith <john@example.com>", True),
        ("john@example.com", "John <JOHN@example.com>", True),
        ("john@example.com", "john@example.com <other@example.com>", False),
        ("UConn", "Careers <careers@uconn.edu>", True),
        ("UConn", "notuconn@example.com", False),
        ("John Smith", "John Johnson <smith@example.com>", False),
    ],
)
def test_people_matching_uses_parsed_addresses_and_whole_tokens(person, header, expected):
    assert (
        email_matches_people(sender_header=header, recipients=[], sender_filter=person) is expected
    )
    assert email_matches_people(sender_header="", recipients=[header], to_filter=person) is expected


def test_exact_address_and_quoted_name_query():
    assert format_person_operator("from", "John Smith") == 'from:"John Smith"'
    assert format_person_operator("from", "John <john@example.com>") == "from:john@example.com"
    query = build_gmail_query(
        sender="john@example.com", to="bob@example.com", raw_query="AWS OR cloud"
    )
    assert query == "from:john@example.com to:bob@example.com (AWS OR cloud)"


def test_no_fallback_drops_explicit_constraints():
    queries = broaden_gmail_queries(
        sender="John",
        to="Sarah",
        keywords="interview",
        subject="Application response",
        after="2024/01/01",
        before="2024/02/01",
        newer_than="7d",
        older_than="1d",
        has_attachment=True,
        in_sent=True,
        raw_query="-in:spam",
    )
    assert len(queries) == 1
    for term in [
        "from:John",
        "to:Sarah",
        'subject:"Application response"',
        "after:",
        "before:",
        "newer_than:7d",
        "older_than:1d",
        "has:attachment",
        "in:sent",
        "-in:spam",
    ]:
        assert term in queries[0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sender": "John OR from:someone"},
        {"to": "John\n"},
        {"after": "2024/02/30"},
        {"after": "3000", "before": "1000"},
        {"newer_than": "-7d"},
        {"older_than": "7d OR in:anywhere"},
        {"raw_query": "(unclosed"},
        {"raw_query": 'subject:"open'},
    ],
)
def test_invalid_query_arguments_are_rejected(kwargs):
    with pytest.raises(ValueError):
        build_gmail_query(**kwargs)


def test_extract_keywords_still_excludes_person_addresses():
    assert (
        "john"
        not in extract_keywords("Find emails from John about project", exclude={"john"}).split()
    )
    assert "john@example.com" not in extract_keywords("from john@example.com about billing")


def test_calendar_windows_honor_timezone_and_dst():
    after, before = calendar_window(
        "yesterday",
        now=datetime(2026, 3, 9, 12, tzinfo=timezone.utc),
        timezone_name="America/New_York",
    )
    assert int(before) - (int(after) + 1) == 23 * 3600
    assert datetime.fromtimestamp(int(after) + 1, timezone.utc) == datetime(
        2026, 3, 8, 5, tzinfo=timezone.utc
    )
    after, before = calendar_window(
        "last_week", now=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), timezone_name="UTC"
    )
    assert datetime.fromtimestamp(int(after) + 1, timezone.utc).date().isoformat() == "2026-09-21"
    assert datetime.fromtimestamp(int(before), timezone.utc).date().isoformat() == "2026-09-28"


def test_search_tool_returns_structured_metadata_and_honest_completeness():
    page = SearchPage(
        messages=[
            EmailSummary(
                id="chosen",
                thread_id="thread1",
                sender="John",
                subject="Interview",
                preview="Invitation",
            )
        ],
        next_page_token="more",
        scanned_count=1,
    )
    with patch.object(client, "search_emails", return_value=page) as search:
        result = search_gmail.invoke(
            {
                "question": "John's response",
                "sender": "John",
                "newer_than": "7d",
                "max_results": 20,
            },
            config=CONFIG,
        )
    assert result["messages"][0]["id"] == "chosen"
    assert "body" not in result["messages"][0]
    assert not result["search_complete"]
    assert search.call_args.kwargs["sender_filter"] == "John"
    assert "newer_than:7d" in search.call_args.args[1]
    json.dumps(result)


@pytest.mark.parametrize(
    "tool,args",
    [
        (search_gmail, {"question": "email", "keywords": "AWS"}),
        (read_email, {"message_id": "chosen"}),
        (read_email_thread, {"thread_id": "thread1"}),
    ],
)
def test_all_gmail_tools_require_injected_identity(tool, args):
    with patch.object(client, "_service") as service:
        result = tool.invoke(args, config={"configurable": {}})
    assert result["status"] == "error" and result["code"] == "not_signed_in"
    service.assert_not_called()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    assert "user_sub" not in tool.tool_call_schema.model_json_schema()["properties"]


def test_tool_errors_are_structured_and_do_not_leak_private_details():
    with patch.object(client, "read_email", side_effect=RuntimeError("token=private")):
        result = read_email.invoke({"message_id": "chosen"}, config=CONFIG)
    assert result["code"] == "api_error" and "private" not in json.dumps(result)
    with patch.object(client, "read_email", side_effect=error()):
        assert read_email.invoke({"message_id": "gone"}, config=CONFIG)["code"] == "not_found"
    with patch.object(client, "search_emails", return_value=SearchPage()):
        assert (
            search_gmail.invoke({"question": "AWS", "keywords": "AWS"}, config=CONFIG)["status"]
            == "no_results"
        )


def test_tool_calendar_window_conflict_is_rejected_before_api_call():
    with patch.object(client, "search_emails") as search:
        result = search_gmail.invoke(
            {"question": "email yesterday", "time_range": "yesterday", "newer_than": "7d"},
            config=CONFIG,
        )
    assert result["code"] == "invalid_arguments"
    search.assert_not_called()


@pytest.mark.parametrize("status", [401, 403])
def test_access_failures_require_reconnection(status):
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.side_effect = error(
        status
    )
    with patch.object(client, "_service", return_value=service):
        result = search_gmail.invoke({"question": "AWS", "keywords": "AWS"}, config=CONFIG)
    assert result["code"] == "not_authorized"


def test_credential_expiry_is_restored_and_missing_expiry_forces_refresh():
    data = {"refresh_token": "synthetic", "token": "synthetic", "expiry": "2099-01-01T00:00:00Z"}
    with patch.object(client, "load_tokens", return_value=data):
        creds = client.credentials_for_user("test-user")
    assert creds.expiry == datetime(2099, 1, 1)
    data.pop("expiry")
    creds = MagicMock()
    with (
        patch.object(client, "load_tokens", return_value=data),
        patch.object(client, "Credentials", return_value=creds),
        patch.object(client, "persist_credentials"),
    ):
        assert client.credentials_for_user("test-user") is creds
    creds.refresh.assert_called_once()
    with (
        patch.object(client, "load_tokens", return_value=data),
        patch.object(client, "Credentials", return_value=creds),
    ):
        creds.refresh.side_effect = RuntimeError("private")
        assert client.credentials_for_user("test-user") is None


def test_optional_email_document_conversion_still_preserves_metadata():
    docs = email_to_documents(
        Email(
            id="chosen", thread_id="thread1", subject="Internship", sender="John", body="Details"
        ),
        user_sub="test-user",
    )
    assert docs[0].metadata["email_id"] == "chosen"
    assert docs[0].metadata["source_type"] == "email"


def test_classifier_receives_followup_context_without_tool_payloads():
    from agents.graph import classifier_node
    from langchain_core.messages import ToolMessage

    with patch("agents.graph.llm") as model:
        structured = model.with_structured_output.return_value
        structured.invoke.return_value = {"route": "private"}
        assert classifier_node(
            {
                "messages": [
                    HumanMessage("Find John's email"),
                    ToolMessage(content="private body", tool_call_id="a"),
                    AIMessage("John replied about the interview"),
                    HumanMessage("What did he say?"),
                ]
            }
        ) == {"route": "private"}
    sent = structured.invoke.call_args.args[0]
    assert any("John replied" in item["content"] for item in sent)
    assert all("private body" not in item["content"] for item in sent)
    assert sent[-1]["content"] == "What did he say?"


def test_document_retrieval_filters_out_archived_email():
    from knowledge.retrieve import retrieve

    with patch("knowledge.retrieve.vector_store") as store:
        retrieve("research", user_sub="test-user")
    assert store.as_retriever.call_args.kwargs["search_kwargs"]["filter"] == {
        "$and": [{"user_sub": "test-user"}, {"source_type": "upload"}]
    }


@pytest.mark.parametrize("expiry", [None, "2020-01-01T00:00:00Z", "malformed"])
def test_real_google_credential_refresh_interface_uses_bounded_transport(expiry):
    data = {"token": "synthetic", "refresh_token": "synthetic", "expiry": expiry}
    with (
        patch.object(client, "load_tokens", return_value=data),
        patch.object(client.Credentials, "refresh", autospec=True) as refresh,
        patch.object(client, "persist_credentials") as persist,
    ):
        creds = client.credentials_for_user("test-user")
    refresh.assert_called_once()
    assert refresh.call_args.args[0] is creds
    assert refresh.call_args.args[1].keywords["timeout"] == 20
    persist.assert_called_once_with("test-user", creds)
