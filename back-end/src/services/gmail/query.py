"""Build Gmail API `q` search strings from structured fields."""

from __future__ import annotations

import re

_STOPWORDS = {
    "a",
    "an",
    "the",
    "my",
    "me",
    "i",
    "i'm",
    "im",
    "find",
    "search",
    "searches",
    "look",
    "looking",
    "email",
    "emails",
    "mail",
    "mailbox",
    "gmail",
    "inbox",
    "message",
    "messages",
    "from",
    "about",
    "did",
    "do",
    "does",
    "receive",
    "received",
    "any",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "there",
    "please",
    "can",
    "could",
    "would",
    "you",
    "your",
    "get",
    "got",
    "show",
    "tell",
    "what",
    "when",
    "where",
    "who",
    "which",
    "have",
    "has",
    "had",
    "in",
    "on",
    "of",
    "to",
    "for",
    "and",
    "or",
    "with",
    "that",
    "this",
    "those",
    "these",
    "it",
    "its",
    "at",
    "by",
    "as",
    "if",
    "into",
    "over",
    "under",
    "last",
    "recent",
    "recently",
}


def _clean(value: str | None) -> str:
    return (value or "").strip()


def extract_keywords(text: str, *, max_terms: int = 8) -> str:
    """Pull meaningful search terms out of a natural-language question."""
    tokens = re.findall(r"[A-Za-z0-9@.+\-]+", (text or "").lower())
    seen: set[str] = set()
    keep: list[str] = []
    for token in tokens:
        if token in _STOPWORDS or len(token) < 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        keep.append(token)
        if len(keep) >= max_terms:
            break
    return " ".join(keep)


def build_gmail_query(
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
    raw_query: str = "",
    quote_subject: bool = False,
) -> str:
    """Assemble a Gmail search query from structured filters + free text.

    Dates should be YYYY/MM/DD (Gmail style). newer_than/older_than use
    Gmail relative forms like ``30d`` or ``1y``.

    Subject is left unquoted by default so multi-word values are AND-matched
    rather than requiring an exact phrase.
    """
    parts: list[str] = []

    sender = _clean(sender)
    if sender:
        parts.append(f"from:{sender}")

    to = _clean(to)
    if to:
        parts.append(f"to:{to}")

    subject = _clean(subject)
    if subject:
        if (
            quote_subject
            and " " in subject
            and not (subject.startswith('"') and subject.endswith('"'))
        ):
            subject = f'"{subject}"'
        parts.append(f"subject:{subject}")

    after = _clean(after).replace("-", "/")
    if after:
        parts.append(f"after:{after}")

    before = _clean(before).replace("-", "/")
    if before:
        parts.append(f"before:{before}")

    newer_than = _clean(newer_than)
    if newer_than:
        parts.append(f"newer_than:{newer_than}")

    older_than = _clean(older_than)
    if older_than:
        parts.append(f"older_than:{older_than}")

    if has_attachment:
        parts.append("has:attachment")

    keywords = _clean(keywords)
    if keywords:
        parts.append(keywords)

    raw_query = _clean(raw_query)
    if raw_query:
        parts.append(raw_query)

    return " ".join(parts)


def broaden_gmail_queries(
    *,
    question: str = "",
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
) -> list[str]:
    """Return increasingly broad Gmail queries (deduped, non-empty)."""
    explicit_keywords = _clean(keywords)
    extracted = extract_keywords(question)
    keyword_text = explicit_keywords or extracted or _clean(question)

    attempts: list[dict] = [
        # 1) Full filters as provided (soft subject matching).
        {
            "keywords": keyword_text,
            "sender": sender,
            "to": to,
            "subject": subject,
            "after": after,
            "before": before,
            "newer_than": newer_than,
            "older_than": older_than,
            "has_attachment": has_attachment,
            "raw_query": raw_query,
        },
        # 2) Drop subject (often over-specific).
        {
            "keywords": keyword_text,
            "sender": sender,
            "to": to,
            "subject": "",
            "after": after,
            "before": before,
            "newer_than": newer_than,
            "older_than": older_than,
            "has_attachment": has_attachment,
            "raw_query": raw_query,
        },
        # 3) Drop people filters.
        {
            "keywords": keyword_text,
            "sender": "",
            "to": "",
            "subject": "",
            "after": after,
            "before": before,
            "newer_than": newer_than,
            "older_than": older_than,
            "has_attachment": False,
            "raw_query": "",
        },
        # 4) Keywords + mild recency only.
        {
            "keywords": keyword_text,
            "newer_than": newer_than or "",
        },
        # 5) Keywords alone.
        {"keywords": keyword_text},
        # 6) OR-join key terms (broader recall).
        {
            "keywords": " OR ".join(keyword_text.split())
            if len(keyword_text.split()) > 1
            else keyword_text
        },
        # 7) Last resort: extracted terms from the question only.
        {"keywords": extracted} if extracted and extracted != keyword_text else {},
    ]

    seen: set[str] = set()
    queries: list[str] = []
    for attempt in attempts:
        if not attempt:
            continue
        q = build_gmail_query(**attempt)
        if not q or q in seen:
            continue
        seen.add(q)
        queries.append(q)
    return queries
