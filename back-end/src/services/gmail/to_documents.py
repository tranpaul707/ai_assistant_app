"""Convert application Email objects into LangChain Documents for RAG ingest."""

from __future__ import annotations

from langchain_core.documents import Document

from services.gmail.models import Email


def email_to_documents(email: Email, *, user_sub: str | None = None) -> list[Document]:
    received = email.received_at.isoformat() if email.received_at else ""
    recipients = ", ".join(email.recipients)
    page_content = (
        f"Subject: {email.subject}\n"
        f"From: {email.sender}\n"
        f"To: {recipients}\n"
        f"Date: {received}\n"
        f"<source: gmail>\n\n"
        f"{email.body}"
    ).strip()

    metadata = {
        "source_type": "email",
        "email_id": email.id,
        "thread_id": email.thread_id,
        "subject": email.subject,
        "sender": email.sender,
        "recipients": recipients,
        "received_at": received,
    }
    if user_sub:
        metadata["user_sub"] = user_sub

    return [Document(page_content=page_content, metadata=metadata)]
