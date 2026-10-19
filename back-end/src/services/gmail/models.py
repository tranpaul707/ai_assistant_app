from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EmailSummary:
    id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    received_at: datetime | None = None
    preview: str = ""
    internal_date_ms: int | None = None
    date_header: str = ""
    cc: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    list_id: str = ""
    auto_submitted: str = ""


@dataclass
class Attachment:
    filename: str
    mime_type: str
    size: int
    attachment_id: str = ""


@dataclass
class Email(EmailSummary):
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    body_truncated: bool = False


@dataclass
class SearchPage:
    messages: list[EmailSummary] = field(default_factory=list)
    next_page_token: str | None = None
    scanned_count: int = 0
    pages_fetched: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class EmailThread:
    id: str
    messages: list[Email] = field(default_factory=list)
    total_messages: int = 0
    truncated: bool = False
    errors: list[dict[str, str]] = field(default_factory=list)


def email_data(email: EmailSummary) -> dict[str, Any]:
    """JSON-compatible tool evidence; summaries deliberately have no body field."""
    data = asdict(email)
    timestamp = data.pop("received_at")
    data["timestamp"] = timestamp.isoformat() if timestamp else None
    data["snippet"] = data.pop("preview")
    return data
