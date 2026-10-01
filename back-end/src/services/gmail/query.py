"""Build Gmail API `q` search strings from structured fields."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
    "sent",
    "send",
    "sending",
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
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "today",
    "yesterday",
}


def _clean(value: str | None) -> str:
    return (value or "").strip()


def is_email_address(value: str) -> bool:
    return bool(_EMAIL_RE.match(_clean(value)))


def format_person_operator(op: str, value: str) -> str:
    """Build ``from:`` / ``to:`` terms. Preserve exact addresses; quote multi-word names."""
    value = _clean(value)
    if not value:
        return ""
    # Strip wrapping angle brackets sometimes pasted from mail clients.
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    if is_email_address(value):
        return f"{op}:{value}"
    if " " in value and not (value.startswith('"') and value.endswith('"')):
        value = f'"{value}"'
    return f"{op}:{value}"


def person_tokens(*people: str) -> set[str]:
    """Token set for excluding person names/addresses from free-text keywords."""
    tokens: set[str] = set()
    for person in people:
        for token in re.findall(r"[A-Za-z0-9@.+\-]+", _clean(person).lower()):
            if len(token) >= 2:
                tokens.add(token)
    return tokens


def extract_keywords(
    text: str,
    *,
    max_terms: int = 8,
    exclude: set[str] | None = None,
) -> str:
    """Pull meaningful search terms out of a natural-language question."""
    skip = set(_STOPWORDS)
    if exclude:
        skip |= {t.lower() for t in exclude}
    tokens = re.findall(r"[A-Za-z0-9@.+\-]+", (text or "").lower())
    seen: set[str] = set()
    keep: list[str] = []
    for token in tokens:
        if token in skip or len(token) < 2:
            continue
        if token in seen:
            continue
        # Don't put email addresses into free-text keywords; those belong in from:/to:.
        if "@" in token:
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
    in_sent: bool = False,
    raw_query: str = "",
    quote_subject: bool = False,
) -> str:
    """Assemble a Gmail search query from structured filters + free text.

    Dates should be YYYY/MM/DD (Gmail style). newer_than/older_than use
    Gmail relative forms like ``30d`` or ``1y``.
    """
    parts: list[str] = []

    sender_term = format_person_operator("from", sender)
    if sender_term:
        parts.append(sender_term)

    to_term = format_person_operator("to", to)
    if to_term:
        parts.append(to_term)

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

    if in_sent:
        parts.append("in:sent")

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
    in_sent: bool = False,
    raw_query: str = "",
) -> list[str]:
    """Return increasingly broad Gmail queries (deduped, non-empty).

    When sender/recipient filters are present, keep them as long as possible —
    dropping ``from:``/``to:`` too early is the main failure mode for
    person-specific searches.
    """
    sender = _clean(sender)
    to = _clean(to)
    explicit_people = bool(sender or to)
    exclude = person_tokens(sender, to)
    explicit_keywords = _clean(keywords)
    extracted = extract_keywords(question, exclude=exclude)
    keyword_text = explicit_keywords or extracted
    # If keywords still contain person tokens, strip them.
    if keyword_text and exclude:
        keyword_text = " ".join(
            tok for tok in keyword_text.split() if tok.lower() not in exclude
        )

    attempts: list[dict] = []

    def add(**kwargs) -> None:
        attempts.append(kwargs)

    # 1) Full structured query.
    add(
        keywords=keyword_text,
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
    # 2) Drop subject (often over-specific).
    add(
        keywords=keyword_text,
        sender=sender,
        to=to,
        after=after,
        before=before,
        newer_than=newer_than,
        older_than=older_than,
        has_attachment=has_attachment,
        in_sent=in_sent,
        raw_query=raw_query,
    )
    # 3) People + topic keywords (+ sent flag), no subject/dates/extras.
    if explicit_people:
        add(
            keywords=keyword_text,
            sender=sender,
            to=to,
            in_sent=in_sent,
        )
        # 4) People + date window only.
        add(
            sender=sender,
            to=to,
            after=after,
            before=before,
            newer_than=newer_than,
            older_than=older_than,
            in_sent=in_sent,
        )
        # 5) People filters alone (critical for "emails from John").
        add(sender=sender, to=to, in_sent=in_sent)
        # 6) Soften exact email → local-part only is dangerous; keep as-is.
        # Last resort: people without in:sent if it was set.
        if in_sent:
            add(sender=sender, to=to, keywords=keyword_text)
            add(sender=sender, to=to)

    # Keyword fallbacks only when no person constraint was given, or as absolute
    # last resort after person-preserving attempts.
    if not explicit_people:
        add(
            keywords=keyword_text,
            after=after,
            before=before,
            newer_than=newer_than,
            older_than=older_than,
            has_attachment=has_attachment,
            raw_query=raw_query,
        )
        add(keywords=keyword_text, newer_than=newer_than or "")
        add(keywords=keyword_text)
        if keyword_text and len(keyword_text.split()) > 1:
            add(keywords=" OR ".join(keyword_text.split()))
        if extracted and extracted != keyword_text:
            add(keywords=extracted)
    else:
        # Absolute last resort if the name/address never matched.
        if keyword_text:
            add(keywords=keyword_text)

    seen: set[str] = set()
    queries: list[str] = []
    for attempt in attempts:
        q = build_gmail_query(**attempt)
        if not q or q in seen:
            continue
        seen.add(q)
        queries.append(q)
    return queries


def email_matches_people(
    *,
    sender_header: str,
    recipients: list[str],
    sender_filter: str = "",
    to_filter: str = "",
) -> bool:
    """Loose post-filter: keep Gmail hits that still match person constraints."""
    sender_filter = _clean(sender_filter).lower()
    to_filter = _clean(to_filter).lower()
    if sender_filter:
        hay = (sender_header or "").lower()
        needle = sender_filter.strip('"')
        if needle not in hay:
            return False
    if to_filter:
        hay = ", ".join(recipients or []).lower()
        needle = to_filter.strip('"')
        if needle not in hay:
            return False
    return True
