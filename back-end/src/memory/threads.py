"""Conversation thread registry (metadata only — message state lives in the checkpointer)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis

from core.settings import REDIS_URI

_LOCAL_OWNER = "local"


def _client() -> redis.Redis:
    return redis.from_url(REDIS_URI, decode_responses=True)


def _owner_key(user_sub: str | None) -> str:
    return f"chat_threads:{(user_sub or _LOCAL_OWNER)}"


def _meta_key(thread_id: str) -> str:
    return f"chat_thread_meta:{thread_id}"


def upsert_thread(
    thread_id: str,
    *,
    title: str | None = None,
    user_sub: str | None = None,
) -> dict[str, Any]:
    """Create or refresh a thread registry entry."""
    r = _client()
    now = datetime.now(timezone.utc).isoformat()
    meta_key = _meta_key(thread_id)
    existing_raw = r.get(meta_key)

    if existing_raw:
        meta = json.loads(existing_raw)
        if title and not meta.get("title"):
            meta["title"] = title[:40]
        meta["updated_at"] = now
        if user_sub and not meta.get("user_sub"):
            meta["user_sub"] = user_sub
    else:
        meta = {
            "thread_id": thread_id,
            "user_sub": user_sub,
            "title": (title or "New chat")[:40],
            "created_at": now,
            "updated_at": now,
        }

    r.set(meta_key, json.dumps(meta))
    score = datetime.now(timezone.utc).timestamp()
    r.zadd(_owner_key(user_sub or meta.get("user_sub")), {thread_id: score})
    # Also index under local so unsigned sessions can list recent chats.
    if user_sub:
        r.zadd(_owner_key(None), {thread_id: score})
    return meta


def list_threads(user_sub: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    r = _client()
    ids = r.zrevrange(_owner_key(user_sub), 0, limit - 1)
    threads: list[dict[str, Any]] = []
    for thread_id in ids:
        raw = r.get(_meta_key(thread_id))
        if raw:
            threads.append(json.loads(raw))
    return threads


def get_thread_meta(thread_id: str) -> dict[str, Any] | None:
    raw = _client().get(_meta_key(thread_id))
    return json.loads(raw) if raw else None
