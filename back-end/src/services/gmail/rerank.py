"""Rank Gmail search hits by similarity to the user's question."""

from __future__ import annotations

import logging
import math
from typing import Sequence

from services.gmail.models import Email

logger = logging.getLogger(__name__)

_BODY_CHARS = 2000


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _email_text(email: Email) -> str:
    body = (email.body or email.preview or "")[:_BODY_CHARS]
    return "\n".join(
        [
            email.subject or "",
            email.sender or "",
            ", ".join(email.recipients or []),
            body,
        ]
    ).strip()


def rerank_emails(
    question: str,
    emails: list[Email],
    *,
    top_k: int = 5,
) -> list[Email]:
    """Return the top_k emails most similar to ``question``.

    Falls back to Gmail's original order if embeddings are unavailable.
    """
    if not emails:
        return []
    if len(emails) <= top_k or not question.strip():
        return emails[:top_k]

    try:
        from knowledge.embeddings import embeddings

        query_vec = embeddings.embed_query(question.strip())
        docs = [_email_text(email) for email in emails]
        doc_vecs = embeddings.embed_documents(docs)
        scored = [
            (_cosine(query_vec, vec), email)
            for email, vec in zip(emails, doc_vecs)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [email for _, email in scored[:top_k]]
    except Exception:
        logger.exception("Email rerank failed; using Gmail order")
        return emails[:top_k]
