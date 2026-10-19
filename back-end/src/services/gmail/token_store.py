"""Authenticated encryption and atomic, private storage for Gmail credentials."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from core.identity import owner_namespace
from core.settings import GMAIL_TOKEN_ENCRYPTION_KEY, OAUTH_DIR

logger = logging.getLogger(__name__)


def token_cipher() -> Fernet:
    """Require a separately managed key; never generate or persist one implicitly."""
    try:
        return Fernet(GMAIL_TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Configure a valid GMAIL_TOKEN_ENCRYPTION_KEY") from exc


def _path_for(sub: str) -> Path:
    return OAUTH_DIR / "v2" / f"{owner_namespace(sub)}.fernet"


def save_tokens(sub: str, data: dict[str, Any]) -> None:
    path = _path_for(sub)
    encrypted = token_cipher().encrypt(
        json.dumps({"version": 2, "user_sub": sub, "data": data}).encode()
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_tokens(sub: str) -> dict[str, Any] | None:
    path = _path_for(sub)
    cipher = token_cipher()
    if not path.exists():
        return None
    try:
        record = json.loads(cipher.decrypt(path.read_bytes()))
        if (
            not isinstance(record, dict)
            or record.get("version") != 2
            or record.get("user_sub") != sub
        ):
            return None
        data = record.get("data")
        return data if isinstance(data, dict) else None
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Gmail credentials could not be decrypted; reconnect required")
        return None


def delete_tokens(sub: str) -> None:
    _path_for(sub).unlink(missing_ok=True)


def has_gmail_tokens(sub: str) -> bool:
    data = load_tokens(sub)
    return bool(data and data.get("refresh_token"))
