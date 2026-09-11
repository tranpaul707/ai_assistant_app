"""Persist Gmail OAuth tokens on disk (never exposed to the frontend)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.settings import OAUTH_DIR


def _path_for(sub: str) -> Path:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    # sub is opaque Google id; sanitize path separators only.
    safe = sub.replace("/", "_").replace("..", "_")
    return OAUTH_DIR / f"{safe}.json"


def save_tokens(sub: str, data: dict[str, Any]) -> None:
    path = _path_for(sub)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_tokens(sub: str) -> dict[str, Any] | None:
    path = _path_for(sub)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_tokens(sub: str) -> None:
    path = _path_for(sub)
    if path.exists():
        path.unlink()


def has_gmail_tokens(sub: str) -> bool:
    data = load_tokens(sub)
    return bool(data and data.get("refresh_token"))
