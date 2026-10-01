"""Mini query agent: rewrite a mailbox question into a better Gmail search."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from llm.client import llm

logger = logging.getLogger(__name__)

_OPTIMIZER_SYSTEM = """You optimize search queries for the Gmail API `q` parameter.

Return structured fields for a precise-but-not-brittle mailbox search.

Critical distinctions:
- sender = who sent the email (Gmail from:). Use for:
  "emails from John", "John sent me", "received from UConn", "from john@x.com"
- to = recipient (Gmail to:). Use for:
  "emails to John", "I sent John", "sent to john@x.com", "emails I sent Bob"
- Never swap sender and to.
- Exact email addresses must go in sender or to unchanged (e.g. john@example.com).
  Do NOT put email addresses into keywords.
- Person/org names for from/to go in sender/to, NOT in keywords.
- keywords: topic/content terms only (project, meeting, internship). No filler words.
  Do not repeat the sender/recipient name inside keywords.
- in_sent=true when the user clearly means mail they sent (Sent folder), e.g.
  "what did I send…", "emails I sent to…". Leave false for normal inbox/received asks.
- Dates: after/before as YYYY/MM/DD; relative windows as newer_than/older_than
  like 7d, 30d, 1y ("last week" → newer_than=7d).
- raw_query: optional extra operators only when helpful (-in:spam, has:attachment).
- Prefer keeping sender/to filled when the user named a person/address.
- Never invent email addresses. A bare name like John or UConn is valid in sender/to.
- rationale: one short sentence explaining the query choice.
"""


class OptimizedGmailSearch(BaseModel):
    keywords: str = Field(
        default="",
        description="Topic/content terms only — not person names or email addresses",
    )
    sender: str = Field(
        default="",
        description="Gmail from: person name or exact email if user means sender",
    )
    to: str = Field(
        default="",
        description="Gmail to: person name or exact email if user means recipient",
    )
    subject: str = Field(default="", description="subject keywords if clearly stated")
    after: str = Field(default="", description="YYYY/MM/DD if clearly stated")
    before: str = Field(default="", description="YYYY/MM/DD if clearly stated")
    newer_than: str = Field(default="", description="e.g. 7d, 30d, 1y")
    older_than: str = Field(default="", description="e.g. 1y")
    has_attachment: bool = Field(default=False)
    in_sent: bool = Field(
        default=False,
        description="True when searching mail the user sent (in:sent)",
    )
    raw_query: str = Field(default="", description="Optional extra Gmail operators")
    rationale: str = Field(default="", description="Short reason for this query")


def _clean(value: str | None) -> str:
    return (value or "").strip()


def merge_search_hints(
    *,
    optimized: OptimizedGmailSearch,
    keywords: str = "",
    sender: str = "",
    to: str = "",
    subject: str = "",
    after: str = "",
    before: str = "",
    newer_than: str = "",
    older_than: str = "",
    has_attachment: bool = False,
    in_sent: bool = False,
    raw_query: str = "",
) -> dict[str, Any]:
    """Prefer caller-provided people/date filters; take optimizer topic keywords/gaps."""
    return {
        "keywords": _clean(keywords) or _clean(optimized.keywords),
        "sender": _clean(sender) or _clean(optimized.sender),
        "to": _clean(to) or _clean(optimized.to),
        "subject": _clean(subject) or _clean(optimized.subject),
        "after": _clean(after) or _clean(optimized.after),
        "before": _clean(before) or _clean(optimized.before),
        "newer_than": _clean(newer_than) or _clean(optimized.newer_than),
        "older_than": _clean(older_than) or _clean(optimized.older_than),
        "has_attachment": bool(has_attachment or optimized.has_attachment),
        "in_sent": bool(in_sent or optimized.in_sent),
        "raw_query": _clean(raw_query) or _clean(optimized.raw_query),
        "rationale": _clean(optimized.rationale),
    }


def optimize_gmail_query(
    question: str,
    *,
    keywords: str = "",
    sender: str = "",
    to: str = "",
    subject: str = "",
    after: str = "",
    before: str = "",
    newer_than: str = "",
    older_than: str = "",
    has_attachment: bool = False,
    in_sent: bool = False,
    raw_query: str = "",
) -> dict[str, Any] | None:
    """Run the mini query agent. Returns merged search fields, or None on failure."""
    hint_lines = [
        f"keywords={keywords!r}" if _clean(keywords) else "",
        f"sender={sender!r}" if _clean(sender) else "",
        f"to={to!r}" if _clean(to) else "",
        f"subject={subject!r}" if _clean(subject) else "",
        f"after={after!r}" if _clean(after) else "",
        f"before={before!r}" if _clean(before) else "",
        f"newer_than={newer_than!r}" if _clean(newer_than) else "",
        f"older_than={older_than!r}" if _clean(older_than) else "",
        "has_attachment=true" if has_attachment else "",
        "in_sent=true" if in_sent else "",
        f"raw_query={raw_query!r}" if _clean(raw_query) else "",
    ]
    hints = "\n".join(line for line in hint_lines if line) or "(none)"

    user_content = (
        f"User question:\n{question.strip()}\n\n"
        f"Optional hints already extracted by the main agent:\n{hints}\n\n"
        "Optimize the Gmail search fields. Put people/addresses in sender/to, "
        "topics in keywords, and set in_sent when the user means sent mail."
    )

    try:
        print("Calling mini agent: optimize_gmail_query")
        structured = llm.with_structured_output(OptimizedGmailSearch)
        result = structured.invoke(
            [
                {"role": "system", "content": _OPTIMIZER_SYSTEM},
                {"role": "user", "content": user_content},
            ]
        )
        if not isinstance(result, OptimizedGmailSearch):
            result = OptimizedGmailSearch.model_validate(result)

        merged = merge_search_hints(
            optimized=result,
            keywords=keywords,
            sender=sender,
            to=to,
            subject=subject,
            after=after,
            before=before,
            newer_than=newer_than,
            older_than=older_than,
            has_attachment=has_attachment,
            in_sent=in_sent,
            raw_query=raw_query,
        )
        logger.info(
            "Gmail query optimizer sender=%r to=%r keywords=%r in_sent=%s rationale=%r",
            merged.get("sender"),
            merged.get("to"),
            merged.get("keywords"),
            merged.get("in_sent"),
            merged.get("rationale"),
        )
        print("Finished mini agent: optimize_gmail_query")
        return merged
    except Exception:
        logger.exception("Gmail query optimizer failed; using original hints")
        print("Finished mini agent: optimize_gmail_query (fallback)")
        return None
