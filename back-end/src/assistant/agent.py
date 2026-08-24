from collections.abc import Awaitable, Callable
from fastapi.routing import request_response
from langchain.agents import create_agent
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command

from llm.client import llm
from memory.checkpointer import get_checkpointer, thread_config
from tools.rag import search_private_knowledge
from langchain.agents.middleware import wrap_tool_call

@wrap_tool_call
def log_tool_calls(request, handler):
    print(f"Calling tool: {request.tool_call['name']}")
    print(f"Finished tool: {request.tool_call['name']}")
    return handler(request)

SYSTEM_PROMPT = """You are a helpful assistant with optional access to a document search tool.

Default behavior: answer from your own knowledge. Do not mention the tool or documents unless you actually used them.

Use rag_search ONLY when ALL of these are true:
1. The user is asking about content that would be in uploaded/stored documents (specific facts, quotes, plot points, names, or details from those files).
2. You cannot confidently answer without looking that content up.
3. The question is not a greeting, small talk, opinion, coding question, or general-knowledge question.

When you do use rag_search:
- Search with a concise query focused on what you need.
- Base your answer only on returned passages. If nothing relevant is found, say so clearly and do not invent document content.
- Never call rag_search more than once unless the first result was empty or clearly off-topic.
"""

def get_agent():
    """Return a process-wide agent graph (created once)."""

    _graph = create_agent(
            model=llm,
            tools=[search_private_knowledge],
            system_prompt=SYSTEM_PROMPT,
            checkpointer=get_checkpointer(),
            middleware=[log_tool_calls],
        )
    return _graph


def stream_agent(query: str, thread_id: str = "user123"):
    """Yield assistant token strings for a conversation thread."""
    graph = get_agent()
    config = thread_config(thread_id)

    for token, _metadata in graph.stream(
        {"messages": [HumanMessage(query)]},
        config=config,
        stream_mode="messages",
    ):
        if isinstance(token, AIMessageChunk) and token.content:
            yield str(token.content)
