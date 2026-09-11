from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Email:
    id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    received_at: datetime | None = None
    body: str = ""
    preview: str = ""
