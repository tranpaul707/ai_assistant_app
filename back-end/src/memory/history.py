"""Load conversation messages from the LangGraph Redis checkpointer."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.agent import looks_like_tool_args_json, message_text
from memory.checkpointer import get_checkpointer, thread_config


def messages_for_thread(thread_id: str) -> list[dict[str, Any]]:
    """Return FE-friendly messages (user/assistant) for a conversation thread."""
    checkpointer = get_checkpointer()
    snapshot = checkpointer.get_tuple(thread_config(thread_id))
    if snapshot is None:
        return []

    channel_values = snapshot.checkpoint.get("channel_values") or {}
    raw_messages = channel_values.get("messages") or []

    result: list[dict[str, Any]] = []
    for index, message in enumerate(raw_messages):
        if isinstance(message, HumanMessage):
            text = message_text(message.content)
            if text.strip():
                result.append(
                    {"id": index, "role": "user", "content": text, "isLoading": False}
                )
        elif isinstance(message, AIMessage):
            # Skip tool-call-only assistant messages.
            if getattr(message, "tool_calls", None):
                continue
            text = message_text(message.content)
            if not text.strip():
                continue
            # Skip leaked tool-argument JSON that some local models store as content.
            if looks_like_tool_args_json(text):
                continue
            result.append(
                {
                    "id": index,
                    "role": "assistant",
                    "content": text,
                    "isLoading": False,
                }
            )
    return result
