"""Memory manager: decide what is worth keeping and reconcile with Redis LTM.

Chroma / RAG is intentionally not used here. Document retrieval and long-term
personal memory are separate concerns; this manager owns memory quality.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from llm.client import llm
from memory import long_term as store

logger = logging.getLogger(__name__)

_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "i",
    "me",
    "my",
    "we",
    "you",
    "your",
    "it",
    "this",
    "that",
    "with",
    "about",
    "from",
    "user",
    "prefers",
    "prefer",
}


class MemoryCandidate(BaseModel):
    type: Literal["fact", "preference"]
    key: str = Field(description="Stable snake_case topic key")
    text: str = Field(description="Concise third-person memory statement")
    worth_keeping: bool = Field(
        description="True only if durable and useful across future chats"
    )
    reason: str = ""


class MemoryDecision(BaseModel):
    action: Literal["keep_new", "replace", "skip"]
    candidate_index: int
    remove_ids: list[str] = Field(
        default_factory=list,
        description="Existing memory ids contradicted or superseded",
    )
    final_key: str = ""
    final_text: str = ""
    reason: str = ""


class MemoryManagerPlan(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    decisions: list[MemoryDecision] = Field(default_factory=list)
    used_memory_ids: list[str] = Field(
        default_factory=list,
        description="Existing memory ids that were relevant to this turn",
    )
    rationale: str = ""


_EXTRACT_SYSTEM = """You are the Memory Manager for a personal knowledge assistant.

Your job is NOT document search. You only manage durable personal memory
(facts and preferences) stored outside the vector DB.

Step 1 — Propose candidates from the latest turn:
- preference: how the user wants answers/behavior
- fact: stable personal facts (name, school, employer, recurring people/projects)
- Set worth_keeping=false for ephemeral chit-chat, one-off questions, email bodies,
  secrets/passwords, tool JSON, or anything not useful in future chats.

Step 2 — For each worth_keeping candidate, look at RELATED EXISTING MEMORIES
(provided) and decide:
- keep_new: no conflict; store it
- replace: contradicts or updates related memories; include remove_ids of old ones
- skip: duplicate / not better than what already exists

Rules:
- Preferences with the same key replace the old preference.
- Facts that contradict older facts must remove the contradicted memories.
- Use short snake_case keys (preferred_name, employer, answer_style, ...).
- final_text must be concise third person ("User prefers concise answers.").
- If nothing durable was learned, return empty candidates/decisions.
- used_memory_ids: ids of existing memories that helped or were relevant this turn.
"""


def _tokens(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return {p for p in parts if len(p) > 2 and p not in _STOP}


def find_related_memories(
    items: list[dict[str, Any]],
    *,
    memory_type: str | None = None,
    key: str = "",
    text: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search existing Redis memories for related entries (no Chroma)."""
    key_n = store.normalize_key(key)
    needle = _tokens(f"{key} {text}")
    scored: list[tuple[int, dict[str, Any]]] = []

    for item in items:
        if memory_type and item.get("type") != memory_type:
            continue
        item_key = store.normalize_key(str(item.get("key") or ""))
        score = 0
        if key_n and item_key == key_n:
            score += 100
        elif key_n and (key_n in item_key or item_key in key_n):
            score += 40
        overlap = needle & _tokens(f"{item_key} {item.get('text') or ''}")
        score += 5 * len(overlap)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def select_for_query(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Choose memories to inject for this turn."""
    prefs = [i for i in items if i.get("type") == "preference"]
    facts = [i for i in items if i.get("type") == "fact"]
    related_facts = find_related_memories(facts, text=query, limit=8)
    if not related_facts and len(facts) <= 8:
        related_facts = facts
    return prefs + related_facts


class MemoryManager:
    """Owns long-term memory policy. Persistence is Redis via ``memory.long_term``."""

    def context_for_turn(
        self, user_sub: str | None, *, query: str = ""
    ) -> tuple[str, list[dict[str, Any]]]:
        if not user_sub:
            return "", []
        items = store.list_active(user_sub)
        if not items:
            return "", []

        selected = select_for_query(items, query)
        if selected:
            store.touch_items(selected)
            by_id = {str(i.get("id")): i for i in selected if i.get("id")}
            merged = [by_id.get(str(i.get("id") or ""), i) for i in items]
            store.persist_items(user_sub, merged)

        return store.format_memory_block(selected), selected

    def ingest_turn(
        self,
        user_sub: str | None,
        *,
        user_message: str,
        assistant_message: str = "",
    ) -> None:
        if not user_sub:
            return
        user_message = (user_message or "").strip()
        if not user_message:
            return

        items = store.list_active(user_sub)
        existing_block = store.format_memory_block(items) or "(no existing memories)"

        # Pre-search related memories for the user message so the LLM can reconcile.
        related = find_related_memories(items, text=user_message, limit=12)
        related_block = store.format_memory_block(related) or "(none)"

        prompt = (
            f"All current memories:\n{existing_block}\n\n"
            f"Related memories for this turn (search result):\n{related_block}\n\n"
            f"User message:\n{user_message}\n\n"
            f"Assistant reply:\n{(assistant_message or '').strip() or '(empty)'}\n\n"
            "Propose candidates, decide keep_new/replace/skip, and list used_memory_ids."
        )

        try:
            print("Calling memory manager")
            plan = llm.with_structured_output(MemoryManagerPlan).invoke(
                [
                    {"role": "system", "content": _EXTRACT_SYSTEM},
                    {"role": "user", "content": prompt},
                ]
            )
            if not isinstance(plan, MemoryManagerPlan):
                plan = MemoryManagerPlan.model_validate(plan)
            self._apply_plan(user_sub, items, plan)
            print("Finished memory manager")
        except Exception:
            logger.exception("Memory manager failed")
            print("Finished memory manager (fallback)")

    def _apply_plan(
        self,
        user_sub: str,
        items: list[dict[str, Any]],
        plan: MemoryManagerPlan,
    ) -> None:
        by_index = {i: c for i, c in enumerate(plan.candidates)}
        remove_ids: list[str] = []
        upserts: list[tuple[str, str, str]] = []

        for decision in plan.decisions:
            if decision.action == "skip":
                continue
            candidate = by_index.get(decision.candidate_index)
            if candidate is None:
                continue
            if not candidate.worth_keeping and decision.action == "keep_new":
                continue

            key = store.normalize_key(decision.final_key or candidate.key)
            text = (decision.final_text or candidate.text or "").strip()
            if not key or not text:
                continue

            if decision.action == "replace":
                remove_ids.extend(decision.remove_ids)
                # Same-key replace is also handled by upsert_memory.
            upserts.append((candidate.type, key, text))
            remove_ids.extend(decision.remove_ids)

        # Also drop candidates marked not worth keeping even if a decision missed.
        # (No-op unless somehow upserted.)

        if plan.used_memory_ids:
            used = [
                i for i in items if str(i.get("id") or "") in set(plan.used_memory_ids)
            ]
            store.touch_items(used)

        if remove_ids:
            items = store.remove_by_ids(items, remove_ids)

        for memory_type, key, text in upserts:
            if memory_type not in ("fact", "preference"):
                continue
            # Same key replaces prior preference/fact (change or contradiction).
            items = store.upsert_memory(
                items,
                memory_type=memory_type,
                key=key,
                text=text,
            )

        items = store.prune_unused(items)
        store.persist_items(user_sub, items)
        logger.info(
            "Memory manager applied user=...%s upserts=%d removals=%d used=%d",
            user_sub[-6:],
            len(upserts),
            len(set(remove_ids)),
            len(plan.used_memory_ids),
        )


# Process-wide manager used by the chat graph.
memory_manager = MemoryManager()
