from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from assistant.agent import get_agent, get_private_agent, is_answer_token
from llm.client import llm
from memory.checkpointer import get_checkpointer, thread_config


class GraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: Literal["general", "private"] | None


class RouteDecision(BaseModel):
    route: Literal["general", "private"]


router_llm = llm.with_structured_output(RouteDecision)


def classify(query: str) -> Literal["general", "private"]:
    decision = router_llm.invoke(
        [
            {
                "role": "system",
                "content": """
                Classify the user's request into exactly one route.

                private = the user wants information from their uploaded/private documents,
                knowledge base, stored files, scripts, or anything that must be looked up
                in personal document storage (including movie scripts or files they mention
                as uploaded/private).

                general = greetings, chit-chat, math, jokes, coding, or anything answerable
                from general world knowledge without searching private documents.

                When unsure whether documents are needed, prefer private.
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


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("classifier", classifier_node)
    builder.add_node("general", get_agent())
    builder.add_node("private", get_private_agent())

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


graph = build_graph()


def stream_routed(query: str, thread_id: str = "user123"):
    """Run the parent graph and yield assistant answer tokens for SSE."""
    config = thread_config(thread_id)

    for namespace, chunk in graph.stream(
        {"messages": [HumanMessage(query)], "route": None},
        config=config,
        stream_mode="messages",
        subgraphs=True,
    ):
        # Parent classifier LLM tokens have an empty namespace; skip them.
        if not namespace:
            continue

        token = chunk[0] if isinstance(chunk, tuple) else chunk
        if is_answer_token(token):
            yield str(getattr(token, "content", ""))
