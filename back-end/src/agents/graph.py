from functools import lru_cache
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from agents.agent import (
    create_general_agent,
    create_private_agent,
    is_answer_token,
    looks_like_tool_args_json,
    message_text,
)
from llm.client import llm
from memory.checkpointer import get_checkpointer, thread_config
from memory.manager import memory_manager


class GraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: Literal["general", "private"] | None


class RouteDecision(BaseModel):
    route: Literal["general", "private"]


def classify(query: str) -> Literal["general", "private"]:
    decision = llm.with_structured_output(RouteDecision).invoke(
        [
            {
                "role": "system",
                "content": """
                Classify the user's request into exactly one route.

                private = the user wants information from their uploaded/private documents,
                knowledge base, stored files, scripts, Gmail/email mailbox, or anything that
                must be looked up in personal document or email storage (including movie
                scripts or files they mention as uploaded/private, and questions like
                "find the email from…", "did I receive…", "search my emails").

                general = greetings, chit-chat, math, jokes, coding, or anything answerable
                from general world knowledge without searching private documents or email.

                When unsure whether documents or email are needed, prefer private.
                """,
            },
            {
                "role": "user",
                "content": query,
            },
        ]
    )
    if isinstance(decision, RouteDecision):
        return decision.route
    if isinstance(decision, dict) and decision.get("route") in ("general", "private"):
        return decision["route"]
    return "general"


def _latest_user_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)


def classifier_node(state: GraphState):
    return {"route": classify(_latest_user_text(state["messages"]))}


def route_request(state: GraphState) -> Literal["general", "private"]:
    return state["route"] or "general"


@lru_cache(maxsize=1)
def get_graph():
    builder = StateGraph(GraphState)
    builder.add_node("classifier", classifier_node)
    builder.add_node("general", create_general_agent())
    builder.add_node("private", create_private_agent())

    builder.add_edge(START, "classifier")
    builder.add_conditional_edges(
        "classifier",
        route_request,
        {
            "general": "general",
            "private": "private",
        },
    )
    builder.add_edge("general", END)
    builder.add_edge("private", END)

    return builder.compile(checkpointer=get_checkpointer())


def stream_routed(
    query: str,
    thread_id: str = "user123",
    *,
    user_sub: str | None = None,
):
    """Run the parent graph and yield assistant answer tokens for SSE."""
    config = thread_config(thread_id, user_sub=user_sub)

    memory_block, _ = memory_manager.context_for_turn(user_sub, query=query)
    turn_messages: list[BaseMessage] = []
    if memory_block:
        turn_messages.append(SystemMessage(content=memory_block))
    turn_messages.append(HumanMessage(query))

    # Local models (e.g. Ollama) often stream tool-call args as plain-text JSON.
    # Buffer `{...}` spans and drop them when they look like tool parameters.
    buf: list[str] = []
    buffering_json = False
    assistant_parts: list[str] = []

    def take_buffer() -> str | None:
        nonlocal buf, buffering_json
        if not buf:
            buffering_json = False
            return None
        joined = "".join(buf)
        buf = []
        buffering_json = False
        if looks_like_tool_args_json(joined):
            return None
        return joined

    for namespace, chunk in get_graph().stream(
        {"messages": turn_messages, "route": None},
        config=config,
        stream_mode="messages",
        subgraphs=True,
    ):
        # Parent classifier LLM tokens have an empty namespace; skip them.
        if not namespace:
            continue

        token = chunk[0] if isinstance(chunk, tuple) else chunk

        if getattr(token, "tool_call_chunks", None) or getattr(token, "tool_calls", None):
            leftover = take_buffer()
            if leftover:
                assistant_parts.append(leftover)
                yield leftover
            continue

        text = message_text(getattr(token, "content", ""))
        if not text:
            continue

        if buffering_json:
            buf.append(text)
            joined = "".join(buf)
            stripped = joined.strip()
            if stripped.startswith("{") and not stripped.endswith("}"):
                continue
            leftover = take_buffer()
            if leftover:
                assistant_parts.append(leftover)
                yield leftover
            continue

        if text.lstrip().startswith("{"):
            buffering_json = True
            buf = [text]
            stripped = text.strip()
            if stripped.endswith("}"):
                leftover = take_buffer()
                if leftover:
                    assistant_parts.append(leftover)
                    yield leftover
            continue

        if looks_like_tool_args_json(text):
            continue

        if not is_answer_token(token):
            continue

        assistant_parts.append(text)
        yield text

    leftover = take_buffer()
    if leftover:
        assistant_parts.append(leftover)
        yield leftover

    # Memory manager decides what is worth keeping (Redis LTM — not Chroma).
    try:
        memory_manager.ingest_turn(
            user_sub,
            user_message=query,
            assistant_message="".join(assistant_parts),
        )
    except Exception:
        pass
