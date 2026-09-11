"""Tests for Redis long-term store + memory manager policy helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from memory import long_term as store
from memory.manager import (
    MemoryCandidate,
    MemoryDecision,
    MemoryManager,
    MemoryManagerPlan,
    find_related_memories,
    select_for_query,
)


def test_prune_unused_drops_stale_memories():
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    fresh = store.new_item(memory_type="fact", key="employer", text="User works at Acme", now=now)
    stale = store.new_item(
        memory_type="fact",
        key="old_school",
        text="User attended Old U",
        now=now - timedelta(days=200),
    )
    kept = store.prune_unused([fresh, stale], now=now)
    assert len(kept) == 1
    assert kept[0]["key"] == "employer"


def test_upsert_replaces_same_key():
    items: list = []
    items = store.upsert_memory(
        items, memory_type="preference", key="answer_style", text="User prefers short answers."
    )
    items = store.upsert_memory(
        items, memory_type="preference", key="answer_style", text="User prefers detailed answers."
    )
    prefs = [i for i in items if i["type"] == "preference" and i["key"] == "answer_style"]
    assert len(prefs) == 1
    assert "detailed" in prefs[0]["text"]


def test_find_related_memories_by_key_and_text():
    items = [
        store.new_item(memory_type="fact", key="employer", text="User works at Acme Corp"),
        store.new_item(memory_type="fact", key="pet_name", text="User has a dog named Rex"),
        store.new_item(
            memory_type="preference", key="answer_style", text="User prefers concise answers"
        ),
    ]
    related = find_related_memories(items, key="employer", text="job at Acme", limit=5)
    assert related
    assert related[0]["key"] == "employer"


def test_select_for_query_includes_preferences():
    items = [
        store.new_item(memory_type="preference", key="tone", text="User prefers friendly tone"),
        store.new_item(memory_type="fact", key="city", text="User lives in Boston"),
        store.new_item(memory_type="fact", key="sport", text="User plays tennis"),
    ]
    selected = select_for_query(items, "what city do I live in?")
    assert any(i["type"] == "preference" for i in selected)
    assert any(i["key"] == "city" for i in selected)


def test_memory_manager_apply_plan_replace_and_skip():
    mgr = MemoryManager()
    items = [
        store.new_item(memory_type="fact", key="employer", text="User works at OldCo"),
    ]
    old_id = items[0]["id"]
    plan = MemoryManagerPlan(
        candidates=[
            MemoryCandidate(
                type="fact",
                key="employer",
                text="User works at NewCo",
                worth_keeping=True,
                reason="job change",
            ),
            MemoryCandidate(
                type="fact",
                key="weather",
                text="It is raining today",
                worth_keeping=False,
                reason="ephemeral",
            ),
        ],
        decisions=[
            MemoryDecision(
                action="replace",
                candidate_index=0,
                remove_ids=[old_id],
                final_key="employer",
                final_text="User works at NewCo",
                reason="contradicts old employer",
            ),
            MemoryDecision(
                action="skip",
                candidate_index=1,
                reason="not worth keeping",
            ),
        ],
        used_memory_ids=[old_id],
    )

    with patch("memory.manager.store.persist_items") as persist:
        mgr._apply_plan("user-sub-1", items, plan)

    saved = persist.call_args.args[1]
    assert len(saved) == 1
    assert saved[0]["text"] == "User works at NewCo"
    assert saved[0]["id"] != old_id
