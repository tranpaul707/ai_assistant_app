"""Build Gmail API `q` search strings from structured fields."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from email.utils import getaddresses, parseaddr
from zoneinfo import ZoneInfo

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
    """Preserve exact addresses; never interpret a person's name as an operator."""
    if len(value) > 500 or any(ord(char) < 32 for char in value):
        raise ValueError("Person filters must be at most 500 characters without control characters")
    value = _clean(value).strip('"')
    if not value:
        return ""
    _, address = parseaddr(value)
    if is_email_address(address):
        return f"{op}:{address}"
    if not re.fullmatch(r"[\w .'+-]+", value):
        raise ValueError("Use a person name or exact email address for sender/to")
    return f'{op}:"{value}"' if " " in value else f"{op}:{value}"


def gmail_timezone() -> str:
    """Server-configured timezone until a validated per-user preference exists."""
    from core.settings import GMAIL_TIMEZONE

    ZoneInfo(GMAIL_TIMEZONE)
    return GMAIL_TIMEZONE


def calendar_window(window: str, *, now: datetime, timezone_name: str) -> tuple[str, str]:
    """Gmail epoch boundaries; last_week is the previous Monday-to-Monday week."""
    local = now.astimezone(ZoneInfo(timezone_name))
    today = local.date()
    if window == "today":
        start, end = today, today + timedelta(days=1)
    elif window == "yesterday":
        start, end = today - timedelta(days=1), today
    elif window == "last_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    else:
        raise ValueError("time_range must be today, yesterday, or last_week")
    zone = ZoneInfo(timezone_name)
    # Gmail after is exclusive; subtract one second to include midnight itself.
    return (
        str(int(datetime.combine(start, time.min, zone).timestamp()) - 1),
        str(int(datetime.combine(end, time.min, zone).timestamp())),
    )


def _date_seconds(value: str, *, timezone_name: str, is_after: bool) -> str:
    value = _clean(value)
    if not value:
        return ""
    if re.fullmatch(r"[0-9]{1,12}", value):
        return value
    try:
        date = datetime.strptime(value.replace("-", "/"), "%Y/%m/%d").date()
    except ValueError:
        raise ValueError("Dates must be YYYY/MM/DD, YYYY-MM-DD, or epoch seconds") from None
    seconds = int(datetime.combine(date, time.min, ZoneInfo(timezone_name)).timestamp())
    return str(seconds - 1 if is_after else seconds)


def _validate_query_text(value: str) -> None:
    if len(value) > 1024 or any(ord(char) < 32 for char in value):
        raise ValueError("Search text must be at most 1024 characters without control characters")
    if value.count('"') % 2:
        raise ValueError("Unclosed quote in Gmail query")
    depth = 0
    quoted = False
    for char in value:
        if char == '"':
            quoted = not quoted
        if quoted:
            continue
        if char in "({":
            depth += 1
        elif char in ")}":
            depth -= 1
        if depth < 0:
            raise ValueError("Unbalanced Gmail query grouping")
    if depth:
        raise ValueError("Unbalanced Gmail query grouping")


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
    timezone_name: str = "UTC",
) -> str:
    """AND structured constraints with grouped native Gmail terms.

    Calendar dates use the configured timezone; epoch boundaries are passed through.
    The main agent plans alternatives explicitly. No automatic constraint dropping.
    """
    parts = [
        term
        for term in (format_person_operator("from", sender), format_person_operator("to", to))
        if term
    ]
    subject = _clean(subject).strip('"')
    if subject:
        _validate_query_text(subject)
        if '"' in subject:
            raise ValueError("Subject must be a plain phrase")
        parts.append(f'subject:"{subject}"')
    after = _date_seconds(after, timezone_name=timezone_name, is_after=True)
    before = _date_seconds(before, timezone_name=timezone_name, is_after=False)
    if after and before and int(after) >= int(before):
        raise ValueError("after must precede before")
    if after:
        parts.append(f"after:{after}")
    if before:
        parts.append(f"before:{before}")
    for operator, value in (("newer_than", newer_than), ("older_than", older_than)):
        if value:
            if not re.fullmatch(r"[1-9][0-9]{0,3}[dmy]", value):
                raise ValueError(f"{operator} must be a positive duration such as 7d or 1y")
            parts.append(f"{operator}:{value}")
    if has_attachment:
        parts.append("has:attachment")
    if in_sent:
        parts.append("in:sent")
    for text in (keywords, raw_query):
        text = _clean(text)
        if text:
            _validate_query_text(text)
            parts.append(f"({text})")
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
    """Compatibility helper: one query preserving every explicit constraint.

    Only absent keyword hints may be extracted from a question. Broadening requires
    another deliberate agent search; people, dates, subject and direction stay intact.
    """
    query = build_gmail_query(
        keywords=keywords
        or (extract_keywords(question, exclude=person_tokens(sender, to)) if not raw_query else ""),
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
    return [query] if query else []


def _person_matches(headers: list[str], person: str) -> bool:
    person = _clean(person).strip('"')
    _, address = parseaddr(person)
    addresses = getaddresses(headers)
    if is_email_address(address):
        return any(candidate.casefold() == address.casefold() for _, candidate in addresses)
    terms = re.findall(r"\w+", person.casefold())
    if not terms:
        return False
    for name, candidate in addresses:
        # Match complete tokens, never John within johnson@newsletter.example.
        for text in (name, candidate):
            tokens = re.findall(r"\w+", text.casefold())
            if any(
                tokens[index : index + len(terms)] == terms
                for index in range(len(tokens) - len(terms) + 1)
            ):
                return True
    return False


def email_matches_people(
    *,
    sender_header: str,
    recipients: list[str],
    sender_filter: str = "",
    to_filter: str = "",
) -> bool:
    """Parsed-address/name post-filter, failing closed on zero matches."""
    return (not sender_filter or _person_matches([sender_header], sender_filter)) and (
        not to_filter or _person_matches(recipients, to_filter)
    )
