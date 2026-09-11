"""Unit tests for Gmail body extraction, document conversion, and tool helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from services.gmail.client import extract_body
from services.gmail.models import Email
from services.gmail.query import build_gmail_query
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


def test_build_gmail_query_operators():
    q = build_gmail_query(
        sender="alice@x.com",
        subject="offer letter",
        after="2026-01-01",
        newer_than="30d",
        has_attachment=True,
        keywords="internship",
        raw_query="-in:spam",
    )
    assert "from:alice@x.com" in q
    # Multi-word subject is not phrase-quoted by default (broader match).
    assert "subject:offer letter" in q
    assert "after:2026/01/01" in q
    assert "newer_than:30d" in q
    assert "has:attachment" in q
    assert "internship" in q
    assert "-in:spam" in q


def test_extract_and_broaden_queries():
    from services.gmail.query import broaden_gmail_queries, extract_keywords

    assert "internship" in extract_keywords("find my emails about the internship offer")
    assert "email" not in extract_keywords("find my email about internship").split()

    queries = broaden_gmail_queries(
        question="Did I get an internship offer email?",
        sender="hr@co.com",
        subject="Final Internship Offer Letter",
        newer_than="7d",
    )
    assert queries
    assert "from:hr@co.com" in queries[0]
    # Later attempts drop strict filters.
    assert any(q == "internship offer" or "internship" in q and "from:" not in q for q in queries)


def test_merge_search_hints_prefers_caller_filters():
    from services.gmail.query_optimizer import OptimizedGmailSearch, merge_search_hints

    optimized = OptimizedGmailSearch(
        keywords="internship offer",
        sender="bot@invented.com",
        subject="made up",
        newer_than="30d",
        rationale="Focus on internship terms",
    )
    merged = merge_search_hints(
        optimized=optimized,
        sender="hr@co.com",
        keywords="",
    )
    assert merged["keywords"] == "internship offer"
    assert merged["sender"] == "hr@co.com"  # caller wins
    assert merged["subject"] == "made up"  # optimizer fills gap
    assert merged["newer_than"] == "30d"
    assert "internship" in merged["rationale"].lower() or merged["rationale"]


def test_search_gmail_unauthorized_without_user():
    from tools.gmail import search_gmail

    result = search_gmail.invoke(
        {"question": "internship"},
        config={"configurable": {}},
    )
    assert "not signed in" in result.lower() or "not available" in result.lower()


def test_search_gmail_uses_query_optimizer():
    from tools.gmail import search_gmail

    email = Email(
        id="e1",
        thread_id="t1",
        subject="Offer",
        sender="hr@co.com",
        body="Congrats on the internship",
    )
    optimized = {
        "keywords": "internship offer",
        "sender": "",
        "to": "",
        "subject": "",
        "after": "",
        "before": "",
        "newer_than": "365d",
        "older_than": "",
        "has_attachment": False,
        "raw_query": "",
        "rationale": "Search internship offer terms",
    }

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=optimized) as opt_mock,
        patch("tools.gmail.search_emails", return_value=[email]) as search_mock,
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {"question": "did I get an internship email?"},
            config={"configurable": {"user_sub": "sub1"}},
        )

    opt_mock.assert_called_once()
    q = search_mock.call_args.args[1]
    assert "internship" in q
    assert "newer_than:365d" in q
    assert "Congrats on the internship" in result
    assert "gmail query" not in result.lower()
    assert "optimizer:" not in result.lower()
    assert "newer_than:" not in result.lower()


def test_search_gmail_returns_context_when_ingest_fails():
    from tools.gmail import search_gmail

    email = Email(
        id="e1",
        thread_id="t1",
        subject="Hello",
        sender="a@b.com",
        body="Body text",
        preview="Body",
    )

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=[email]),
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest", side_effect=RuntimeError("chroma down")),
    ):
        result = search_gmail.invoke(
            {
                "question": "hello message",
                "keywords": "hello",
                "sender": "a@b.com",
            },
            config={"configurable": {"user_sub": "sub1"}},
        )

    assert "Body text" in result
    assert "gmail query" not in result.lower()


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
    assert "tried queries" not in result.lower()


def test_search_gmail_broadens_when_strict_query_empty():
    from tools.gmail import search_gmail

    email = Email(
        id="2",
        thread_id="t2",
        subject="Internship offer",
        sender="hr@co.com",
        body="You got the offer",
    )

    def fake_search(_sub, query, max_results=15):
        # Strict first query includes invented subject → empty; broader hits.
        if "subject:" in query:
            return []
        return [email]

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", side_effect=fake_search),
        patch("tools.gmail.rerank_emails", side_effect=lambda q, emails, top_k=5: emails[:top_k]),
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {
                "question": "internship offer",
                "subject": "Final Internship Offer Letter",
                "sender": "nobody@example.com",
            },
            config={"configurable": {"user_sub": "sub1"}},
        )

    assert "You got the offer" in result
    assert "broadened" not in result.lower()
    assert "gmail query" not in result.lower()


def test_search_gmail_fetches_wide_then_reranks():
    from tools.gmail import search_gmail

    emails = [
        Email(id="1", thread_id="t1", subject="Noise", sender="x@y.com", body="unrelated"),
        Email(
            id="2",
            thread_id="t2",
            subject="Internship offer",
            sender="hr@co.com",
            body="You got the offer",
        ),
        Email(id="3", thread_id="t3", subject="Newsletter", sender="n@n.com", body="sale"),
    ]

    with (
        patch("tools.gmail.optimize_gmail_query", return_value=None),
        patch("tools.gmail.search_emails", return_value=emails) as search_mock,
        patch(
            "tools.gmail.rerank_emails",
            return_value=[emails[1]],
        ) as rerank_mock,
        patch("tools.gmail.ingest"),
    ):
        result = search_gmail.invoke(
            {
                "question": "internship offer email",
                "keywords": "internship offer",
                "subject": "offer",
            },
            config={"configurable": {"user_sub": "sub1"}},
        )

    assert search_mock.call_args.kwargs.get("max_results") == 15
    rerank_mock.assert_called_once()
    assert "You got the offer" in result
    assert "Noise" not in result
