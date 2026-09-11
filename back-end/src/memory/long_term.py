"""Redis persistence for long-term user memories (storage only).

Judgment about what is worth keeping lives in ``memory.manager.MemoryManager``,
not here and not in Chroma.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import redis

from core.settings import REDIS_URI

logger = logging.getLogger(__name__)

MemoryType = Literal["fact", "preference"]

# Unused memories expire after ~5–6 months.
UNUSED_AFTER = timedelta(days=180)

_KEY_PREFIX = "ltm:user:"


def _client() -> redis.Redis:
    return redis.from_url(REDIS_URI, decode_responses=True)


def _redis_key(user_sub: str) -> str:
    safe = user_sub.replace("/", "_").replace(":", "_")
    return f"{_KEY_PREFIX}{safe}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def empty_store() -> dict[str, Any]:
    return {"version": 1, "items": []}


def load_raw(user_sub: str) -> dict[str, Any]:
    if not user_sub:
        return empty_store()
    raw = _client().get(_redis_key(user_sub))
    if not raw:
        return empty_store()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Corrupt LTM payload for user; resetting")
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def save_raw(user_sub: str, data: dict[str, Any]) -> None:
    if not user_sub:
        return
    payload = {
        "version": int(data.get("version") or 1),
        "items": list(data.get("items") or []),
        "updated_at": _iso(_now()),
    }
    _client().set(_redis_key(user_sub), json.dumps(payload))


def prune_unused(
    items: list[dict[str, Any]], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Drop memories not used for UNUSED_AFTER (~6 months)."""
    cutoff = (now or _now()) - UNUSED_AFTER
    kept: list[dict[str, Any]] = []
    for item in items:
        last = _parse_dt(item.get("last_used_at")) or _parse_dt(item.get("updated_at"))
        if last is None or last >= cutoff:
            kept.append(item)
    return kept


def touch_items(
    items: list[dict[str, Any]], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    stamp = _iso(now or _now())
    for item in items:
        item["last_used_at"] = stamp
    return items


def normalize_key(key: str) -> str:
    return (key or "").strip().lower().replace(" ", "_").replace("-", "_")


def format_memory_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    facts = [i for i in items if i.get("type") == "fact"]
    prefs = [i for i in items if i.get("type") == "preference"]
    lines = [
        "Long-term memory about this user (stable facts and preferences).",
        "Use silently to personalize answers and searches. Do not dump this list unless asked.",
    ]
    if prefs:
        lines.append("Preferences:")
        for item in prefs:
            lines.append(f"- [{item.get('key')}] {item.get('text')}")
    if facts:
        lines.append("Facts:")
        for item in facts:
            lines.append(f"- [{item.get('key')}] {item.get('text')}")
    return "\n".join(lines)


def new_item(
    *,
    memory_type: MemoryType,
    key: str,
    text: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = _iso(now or _now())
    return {
        "id": str(uuid.uuid4()),
        "type": memory_type,
        "key": normalize_key(key),
        "text": text.strip(),
        "created_at": stamp,
        "updated_at": stamp,
        "last_used_at": stamp,
    }


def upsert_memory(
    items: list[dict[str, Any]],
    *,
    memory_type: MemoryType,
    key: str,
    text: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Insert or replace by (type, key). Same key removes the prior entry."""
    key = normalize_key(key)
    text = (text or "").strip()
    if not key or not text:
        return items
    remaining = [
        item
        for item in items
        if not (
            item.get("type") == memory_type
            and normalize_key(str(item.get("key") or "")) == key
        )
    ]
    remaining.append(new_item(memory_type=memory_type, key=key, text=text, now=now))
    return remaining


def remove_by_ids(items: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    drop = {i for i in ids if i}
    if not drop:
        return items
    return [item for item in items if str(item.get("id") or "") not in drop]


def remove_by_keys(
    items: list[dict[str, Any]],
    *,
    memory_type: MemoryType | None = None,
    keys: list[str],
) -> list[dict[str, Any]]:
    normalized = {normalize_key(k) for k in keys if k}
    if not normalized:
        return items
    out: list[dict[str, Any]] = []
    for item in items:
        item_key = normalize_key(str(item.get("key") or ""))
        if item_key in normalized and (
            memory_type is None or item.get("type") == memory_type
        ):
            continue
        out.append(item)
    return out


def list_active(user_sub: str) -> list[dict[str, Any]]:
    """Load and prune unused memories for a user."""
    if not user_sub:
        return []
    data = load_raw(user_sub)
    items = prune_unused(list(data.get("items") or []))
    if len(items) != len(data.get("items") or []):
        data["items"] = items
        save_raw(user_sub, data)
    return items


def persist_items(user_sub: str, items: list[dict[str, Any]]) -> None:
    if not user_sub:
        return
    save_raw(user_sub, {"version": 1, "items": items})
