"""Owner-scoped thread registry with atomic, immutable ownership reservations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis

from core.identity import owner_namespace, validate_thread_id
from core.settings import REDIS_URI

# Ownership reservation and registry/index update commit in one Redis script.
# Reject legacy IDs and damaged/missing metadata rather than claiming them.
_UPSERT = """
if redis.call('EXISTS', KEYS[4]) == 1 then return -1 end
local owner = redis.call('GET', KEYS[1])
local raw = redis.call('GET', KEYS[2])
if owner and owner ~= ARGV[1] then return -1 end
if owner and not raw then return -1 end
local meta
if raw then
    local ok
    ok, meta = pcall(cjson.decode, raw)
    if not ok or type(meta) ~= 'table' or meta.user_sub ~= ARGV[2]
        or meta.thread_id ~= ARGV[3] or not owner then return -1 end
    meta.updated_at = ARGV[4]
else
    meta = cjson.decode(ARGV[6])
    redis.call('SET', KEYS[1], ARGV[1])
end
local encoded = cjson.encode(meta)
redis.call('SET', KEYS[2], encoded)
redis.call('ZADD', KEYS[3], ARGV[5], ARGV[3])
return encoded
"""


def _client() -> redis.Redis:
    return redis.from_url(REDIS_URI, decode_responses=True)


def _owner_key(user_sub: str) -> str:
    return f"chat:v2:{owner_namespace(user_sub)}:threads"


def _meta_key(thread_id: str, user_sub: str) -> str:
    return f"chat:v2:{owner_namespace(user_sub)}:meta:{validate_thread_id(thread_id)}"


def _claim_key(thread_id: str) -> str:
    return f"chat:v2:owner:{validate_thread_id(thread_id)}"


def upsert_thread(thread_id: str, *, user_sub: str, title: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    meta = {
        "thread_id": validate_thread_id(thread_id),
        "user_sub": user_sub,
        "title": (title or "New chat")[:40],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    result = _client().eval(
        _UPSERT,
        4,
        _claim_key(thread_id),
        _meta_key(thread_id, user_sub),
        _owner_key(user_sub),
        f"chat_thread_meta:{thread_id}",
        owner_namespace(user_sub),
        user_sub,
        thread_id,
        now.isoformat(),
        now.timestamp(),
        json.dumps(meta),
    )
    if not isinstance(result, (str, bytes, bytearray)):
        raise PermissionError("Thread not accessible")
    return json.loads(result)


def get_thread_meta(thread_id: str, *, user_sub: str) -> dict[str, Any] | None:
    r = _client()
    records = r.mget(_claim_key(thread_id), _meta_key(thread_id, user_sub))
    if not isinstance(records, list) or len(records) != 2:
        return None
    owner, raw = records
    if owner != owner_namespace(user_sub) or not raw:
        return None
    try:
        meta = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(meta, dict)
        or meta.get("user_sub") != user_sub
        or meta.get("thread_id") != thread_id
    ):
        return None
    return meta


def require_thread_owner(thread_id: str, *, user_sub: str) -> dict[str, Any]:
    meta = get_thread_meta(thread_id, user_sub=user_sub)
    if meta is None:
        raise PermissionError("Thread not accessible")
    return meta


def list_threads(user_sub: str, *, limit: int = 50) -> list[dict[str, Any]]:
    r = _client()
    ids = r.zrevrange(_owner_key(user_sub), 0, max(1, min(limit, 100)) - 1)
    if not isinstance(ids, list):
        raise RuntimeError("Invalid thread registry response")
    result = []
    for thread_id in ids:
        try:
            meta = get_thread_meta(thread_id, user_sub=user_sub)
        except ValueError:
            continue
        if meta is not None:
            result.append(meta)
    return result
