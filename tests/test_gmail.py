"""Unit tests for Gmail body extraction, query building, and search_gmail."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from services.gmail.client import extract_body
from services.gmail.models import Email
from services.gmail.query import (
    broaden_gmail_queries,
    build_gmail_query,
    email_matches_people,
    extract_keywords,
    format_person_operator,
)
from services.gmail.to_documents import email_to_documents


def test_extract_body_prefers_plain_text():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {
                    "data": __import__("base64")
                    .urlsafe_b64encode(b"Hello plain")
                    .decode()
                    .rstrip("=")
                },
            },
            {
                "mimeType": "text/html",
                "body": {
                    "data": __import__("base64")
                    .urlsafe_b64encode(b"<p>Hello html</p>")
                    .decode()
                    .rstrip("=")
                },
            },
        ],
    }
    assert extract_body(payload) == "Hello plain"


def test_extract_body_falls_back_to_html():
    html = "<p>Hi <b>there</b></p>"
    payload = {
        "mimeType": "text/html",
        "body": {
            "data": __import__("base64").urlsafe_b64encode(html.encode()).decode().rstrip("=")
        },
    }
    assert "Hi" in extract_body(payload)
    assert "<p>" not in extract_body(payload)


def test_email_to_documents_metadata():
    email = Email(
        id="msg123",
        thread_id="thr1",
        subject="Internship",
        sender="John <john@example.com>",
        recipients=["paul@example.com"],
        received_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        body="See details attached.",
        preview="See details",
    )
    docs = email_to_documents(email, user_sub="user-sub")
    assert len(docs) == 1
    assert "Subject: Internship" in docs[0].page_content
    assert docs[0].metadata["email_id"] == "msg123"
    assert docs[0].metadata["source_type"] == "email"
    assert docs[0].metadata["user_sub"] == "user-sub"


def test_build_gmail_query_exact_sender_and_recipient_addresses():
    q = build_gmail_query(sender="john@example.com", to="bob@example.com", keywords="project")
    assert "from:john@example.com" in q
    assert "to:bob@example.com" in q
    assert "project" in q


def test_format_person_operator_quotes_multiword_names():
    assert format_person_operator("from", "John Smith") == 'from:"John Smith"'
    assert format_person_operator("to", "john@example.com") == "to:john@example.com"


def test_extract_keywords_excludes_person_tokens_and_emails():
    text = "Find emails from John about the project meeting"
    assert "project" in extract_keywords(text, exclude={"john"})
    assert "john" not in extract_keywords(text, exclude={"john"}).split()
    assert "john@example.com" not in extract_keywords(
        "emails from john@example.com about billing"
    )


def test_broaden_keeps_sender_as_long_as_possible():
    queries = broaden_gmail_queries(
        question="Find emails from John about the project",
        sender="John",
        keywords="project",
    )
    assert queries
    assert "from:John" in queries[0]
    # Person-preserving attempts should dominate; people-only must appear.
    assert any(q.strip() == "from:John" for q in queries)
    # Must not jump straight to keyword-only before trying people-only.
    people_only_idx = next(i for i, q in enumerate(queries) if q.strip() == "from:John")
    keyword_only_idxs = [i for i, q in enumerate(queries) if "from:" not in q]
    if keyword_only_idxs:
        assert people_only_idx < keyword_only_idxs[0]


def test_broaden_recipient_and_in_sent():
    queries = broaden_gmail_queries(
        question="What did I send Sarah about the meeting?",
        to="Sarah",
        keywords="meeting",
        in_sent=True,
    )
    assert any("to:Sarah" in q and "in:sent" in q for q in queries)
    assert any(q.strip() == "to:Sarah in:sent" for q in queries)


def test_broaden_sender_and_date():
    queries = broaden_gmail_queries(
        question="What did Sarah send me last week?",
        sender="Sarah",
        newer_than="7d",
    )
    assert any("from:Sarah" in q and "newer_than:7d" in q for q in queries)


def test_broaden_sender_and_recipient():
    queries = broaden_gmail_queries(sender="Alice", to="Bob", keywords="invoice")
    assert "from:Alice" in queries[0] and "to:Bob" in queries[0]


def test_broaden_normal_search_without_people():
    queries = broaden_gmail_queries(question="internship offer", keywords="internship offer")
    assert queries
    assert "from:" not in queries[0]
    assert "internship" in queries[0]


def test_email_matches_people_filter():
    assert email_matches_people(
        sender_header="John Doe <john@example.com>",
        recipients=["me@x.com"],
        sender_filter="john@example.com",
    )
    assert email_matches_people(
        sender_header="me@x.com",
        recipients=["Sarah Connor <sarah@x.com>"],
        to_filter="Sarah",
    )
    assert not email_matches_people(
        sender_header="Other <other@x.com>",
        recipients=["me@x.com"],
        sender_filter="John",
    )


def test_merge_search_hints_prefers_caller_people_filters():
    from services.gmail.query_optimizer import OptimizedGmailSearch, merge_search_hints

    optimized = OptimizedGmailSearch(
        keywords="project",
        sender="bot@invented.com",
        to="",
        newer_than="30d",
        rationale="Focus on project",
    )
    merged = merge_search_hints(
        optimized=optimized,
        sender="hr@co.com",
        keywords="",
    )
    assert merged["keywords"] == "project"
    assert merged["sender"] == "hr@co.com"
    assert merged["newer_than"] == "30d"


def test_search_gmail_unauthorized_without_user():
    from tools.gmail import search_gmail

    result = search_gmail.invoke(
        {"question": "internship"},
        config={"configurable": {}},
    )
    assert "not signed in" in result.lower() or "not available" in result.lower()


def test_search_gmail_from_exact_email():
    from tools.gmail import search_gmail

    email = Email(
        id="e1",
        thread_id="t1",
        subject="Hello",
        sender="John <john@example.com>",
        recipients=["me@x.com"],
        body="Hi there",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {"question": "emails from john@example.com", "sender": "john@example.com"},
            config={"configurable": {"user_sub": "sub1"}},
        )
    assert "from:john@example.com" in search_mock.call_args.args[1]
    assert "Hi there" in result


def test_search_gmail_to_exact_email_in_sent():
    from tools.gmail import search_gmail

    email = Email(
        id="e2",
        thread_id="t2",
        subject="Ping",
        sender="me@x.com",
        recipients=["john@example.com"],
        body="Sent body",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {
                "question": "emails I sent to john@example.com",
                "to": "john@example.com",
                "in_sent": True,
            },
            config={"configurable": {"user_sub": "sub1"}},
        )
    q = search_mock.call_args.args[1]
    assert "to:john@example.com" in q
    assert "in:sent" in q
    assert "Sent body" in result


def test_search_gmail_from_named_person_plus_keyword():
    from tools.gmail import search_gmail

    email = Email(
        id="e3",
        thread_id="t3",
        subject="Project update",
        sender="John <j@x.com>",
        recipients=["me@x.com"],
        body="Project status",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {
                "question": "Find emails from John about the project",
                "sender": "John",
                "keywords": "project",
            },
            config={"configurable": {"user_sub": "sub1"}},
        )
    q = search_mock.call_args.args[1]
    assert "from:John" in q
    assert "project" in q
    assert "Project status" in result


def test_search_gmail_to_named_person_plus_keyword():
    from tools.gmail import search_gmail

    email = Email(
        id="e4",
        thread_id="t4",
        subject="Meeting",
        sender="me@x.com",
        recipients=["Bob <bob@x.com>"],
        body="About the meeting",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {
                "question": "Find emails I sent to Bob about the meeting",
                "to": "Bob",
                "keywords": "meeting",
                "in_sent": True,
            },
            config={"configurable": {"user_sub": "sub1"}},
        )
    q = search_mock.call_args.args[1]
    assert "to:Bob" in q
    assert "meeting" in q
    assert "About the meeting" in result


def test_search_gmail_sender_date_range():
    from tools.gmail import search_gmail

    email = Email(
        id="e5",
        thread_id="t5",
        subject="Weekly",
        sender="Sarah <s@x.com>",
        recipients=["me@x.com"],
        body="Last week note",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        search_gmail.invoke(
            {
                "question": "What did Sarah send me last week?",
                "sender": "Sarah",
                "newer_than": "7d",
            },
            config={"configurable": {"user_sub": "sub1"}},
        )
    q = search_mock.call_args.args[1]
    assert "from:Sarah" in q
    assert "newer_than:7d" in q


def test_search_gmail_filters_nonmatching_sender_hits():
    from tools.gmail import search_gmail

    emails = [
        Email(id="1", thread_id="t", subject="A", sender="Other <o@x.com>", body="nope"),
        Email(id="2", thread_id="t", subject="B", sender="John <j@x.com>", body="yes"),
    ]
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=emails),
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {"question": "emails from John", "sender": "John"},
            config={"configurable": {"user_sub": "sub1"}},
        )
    assert "yes" in result
    assert "nope" not in result


def test_search_gmail_ingests_into_chroma_with_email_source():
    from tools.gmail import search_gmail

    email = Email(
        id="ingest1",
        thread_id="t",
        subject="S",
        sender="a@b.com",
        body="Body",
    )
    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]),
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest") as ingest_mock,
    ):
        search_gmail.invoke(
            {"question": "hello", "keywords": "hello"},
            config={"configurable": {"user_sub": "sub1"}},
        )
    ingest_mock.assert_called_once()
    assert ingest_mock.call_args.args[1] == "email:ingest1"


def test_search_gmail_duplicate_ingest_uses_same_source_key():
    """Re-retrieving the same Gmail id should ingest under the same source key."""
    from knowledge.ingest import ingest
    from langchain_core.documents import Document

    docs = [Document(page_content="hello world " * 20, metadata={"email_id": "dup1"})]
    store = MagicMock()
    store.get.return_value = {"ids": ["email:dup1-0"]}
    chunks = [Document(page_content="chunk-a", metadata={})]

    with (
        patch("knowledge.ingest.vector_store", store),
        patch("knowledge.ingest.chunk_text", return_value=chunks),
    ):
        ingest(docs, "email:dup1")
        ingest(docs, "email:dup1")

    assert store.delete.call_count == 2
    assert all(
        call.kwargs["ids"] == ["email:dup1-0"] for call in store.add_documents.call_args_list
    )


def test_search_gmail_api_failure_does_not_raise():
    from tools.gmail import search_gmail

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", side_effect=RuntimeError("boom")),
    ):
        result = search_gmail.invoke(
            {"question": "emails from John", "sender": "John"},
            config={"configurable": {"user_sub": "sub1"}},
        )
    assert "failed" in result.lower()


def test_search_gmail_no_results():
    from tools.gmail import search_gmail

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[]),
    ):
        result = search_gmail.invoke(
            {"question": "zzz", "keywords": "zzz"},
            config={"configurable": {"user_sub": "sub1"}},
        )
    assert "no matching" in result.lower()


def test_classifier_prefers_private_for_email_questions():
    from agents.graph import classify

    with patch("agents.graph.llm") as mock_llm:
        structured = MagicMock()
        structured.invoke.return_value = {"route": "private"}
        mock_llm.with_structured_output.return_value = structured
        assert classify("Find emails from John about the project") == "private"
        # Non-email general question still classifiable as general.
        structured.invoke.return_value = {"route": "general"}
        assert classify("What is the capital of France?") == "general"
