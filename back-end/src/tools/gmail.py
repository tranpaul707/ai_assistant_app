from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from knowledge.ingest import ingest
from services.gmail.client import search_emails
from services.gmail.query import broaden_gmail_queries
from services.gmail.query_optimizer import optimize_gmail_query
from services.gmail.rerank import rerank_emails
from services.gmail.to_documents import email_to_documents

logger = logging.getLogger(__name__)

# Fetch a wider candidate set from Gmail, then keep the best after rerank.
_FETCH_LIMIT = 15
_RETURN_TOP_K = 5


def _user_sub(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable") or {}
    sub = configurable.get("user_sub")
    return str(sub) if sub else None


def _format_emails(emails) -> str:
    blocks = []
    for email in emails:
        received = email.received_at.isoformat() if email.received_at else ""
        blocks.append(
            "\n".join(
                [
                    f"Subject: {email.subject}",
                    f"From: {email.sender}",
                    f"To: {', '.join(email.recipients)}",
                    f"Date: {received}",
                    "",
                    email.body or email.preview or "(empty body)",
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


@tool(
    "search_gmail",
    description=(
        "Search the user's Gmail mailbox. Set question to the user's intent. "
        "Optional filters (sender, subject, dates, keywords) are hints — a "
        "query optimizer rewrites them into a better Gmail search automatically. "
        "Only pass filters the user clearly stated; do not invent them."
    ),
    response_format="content",
)
def search_gmail(
    question: str,
    config: Annotated[RunnableConfig, InjectedToolArg],
    keywords: str = "",
    sender: str = "",
    to: str = "",
    subject: str = "",
    after: str = "",
    before: str = "",
    newer_than: str = "",
    older_than: str = "",
    has_attachment: bool = False,
    raw_query: str = "",
) -> str:
    """Optimize the Gmail query, search with fallbacks, rerank, return email text."""
    user_sub = _user_sub(config)
    if not user_sub:
        return (
            "Gmail is not available: the user is not signed in. "
            "Ask them to sign in with Google and connect Gmail."
        )

    optimized = optimize_gmail_query(
        question,
        keywords=keywords,
        sender=sender,
        to=to,
        subject=subject,
        after=after,
        before=before,
        newer_than=newer_than,
        older_than=older_than,
        has_attachment=has_attachment,
        raw_query=raw_query,
    )

    search_args = {
        "question": question,
        "keywords": keywords,
        "sender": sender,
        "to": to,
        "subject": subject,
        "after": after,
        "before": before,
        "newer_than": newer_than,
        "older_than": older_than,
        "has_attachment": has_attachment,
        "raw_query": raw_query,
    }
    optimizer_note = ""
    if optimized:
        optimizer_note = optimized.pop("rationale", "") or ""
        search_args.update(
            {
                "keywords": optimized.get("keywords", ""),
                "sender": optimized.get("sender", ""),
                "to": optimized.get("to", ""),
                "subject": optimized.get("subject", ""),
                "after": optimized.get("after", ""),
                "before": optimized.get("before", ""),
                "newer_than": optimized.get("newer_than", ""),
                "older_than": optimized.get("older_than", ""),
                "has_attachment": bool(optimized.get("has_attachment")),
                "raw_query": optimized.get("raw_query", ""),
            }
        )

    queries = broaden_gmail_queries(**search_args)

    if not queries:
        return (
            "Need a clearer email search. Ask for sender, subject keywords, "
            "or a time range."
        )

    emails = []
    used_query = queries[0]
    tried: list[str] = []

    try:
        for gmail_q in queries:
            tried.append(gmail_q)
            logger.info("Gmail search q=%r", gmail_q)
            emails = search_emails(user_sub, gmail_q, max_results=_FETCH_LIMIT)
            if emails:
                used_query = gmail_q
                break
    except PermissionError:
        return (
            "Gmail is not authorized. Ask the user to click Connect Gmail "
            "and grant read-only mailbox access."
        )
    except Exception:
        logger.exception("Gmail search failed")
        return "Gmail search failed due to an API error. Try again later."

    if not emails:
        logger.info("Gmail search empty; tried=%s", tried)
        return (
            "No matching emails were found. "
            "Ask for different keywords, sender, or a broader time range."
        )

    ranked = rerank_emails(question or keywords or used_query, emails, top_k=_RETURN_TOP_K)

    ingested = 0
    for email in ranked:
        try:
            docs = email_to_documents(email, user_sub=user_sub)
            ingest(docs, f"email:{email.id}")
            ingested += 1
        except Exception:
            logger.exception("Failed to ingest email id=%s", email.id)

    logger.info(
        "Gmail search ok query=%r optimized=%r broadened=%s candidates=%d returned=%d ingested=%d",
        used_query,
        optimizer_note or None,
        used_query != queries[0],
        len(emails),
        len(ranked),
        ingested,
    )
    # Return email content only — never append query/optimizer metadata (the
    # model tends to echo those brackets into the user-visible answer).
    return _format_emails(ranked)
