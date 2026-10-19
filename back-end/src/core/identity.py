"""Validated identity and collision-resistant private storage namespaces."""

from hashlib import sha256
import re
from uuid import UUID


def require_identity(user_sub: object) -> str:
    """Accept only an opaque identity supplied by verified request/tool context."""
    if not isinstance(user_sub, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", user_sub):
        raise ValueError("A verified user identity is required")
    return user_sub


def owner_namespace(user_sub: str) -> str:
    return sha256(require_identity(user_sub).encode()).hexdigest()


def validate_thread_id(thread_id: str) -> str:
    """Require a canonical UUID; never interpolate arbitrary IDs into Redis keys."""
    if not isinstance(thread_id, str) or len(thread_id) != 36:
        raise ValueError("Thread ID must be a canonical UUID")
    try:
        canonical = str(UUID(thread_id))
    except ValueError as exc:
        raise ValueError("Thread ID must be a canonical UUID") from exc
    if canonical != thread_id:
        raise ValueError("Thread ID must be a canonical UUID")
    return canonical
