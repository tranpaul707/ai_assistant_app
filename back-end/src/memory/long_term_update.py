"""Backward-compatible wrapper — prefer ``memory.manager.memory_manager``."""

from __future__ import annotations

from memory.manager import memory_manager


def update_long_term_from_turn(
    user_sub: str | None,
    *,
    user_message: str,
    assistant_message: str = "",
) -> None:
    memory_manager.ingest_turn(
        user_sub,
        user_message=user_message,
        assistant_message=assistant_message,
    )
