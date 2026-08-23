from typing import Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.redis import RedisSaver
from langgraph.graph import MessagesState
from llm.client import llm


def format_response(result: dict) -> str:
    lines: list[str] = []
    for msg in result.get("messages", []):
        if isinstance(msg, HumanMessage):
            lines.append(f"Human: {msg.content}")
        elif isinstance(msg, AIMessage):
            if msg.content:
                lines.append(f"AI: {msg.content}")
    return "\n".join(lines)


def lang_graph_redis_short_term(query: str):
    REDIS_URI = "redis://localhost:6379"
    with RedisSaver.from_conn_string(REDIS_URI) as checkpointer:
        checkpointer.setup()

        graph = create_agent(model=llm, checkpointer=checkpointer)

        config: RunnableConfig = {"configurable": {"thread_id": "user123"}}
        res = graph.invoke(
            {"messages": [HumanMessage(query)]},
            config, stream_mode="values",
        )

        ai_message = res["messages"][-1]

        print(ai_message.content)

lang_graph_redis_short_term("Who was known to be the tallest person in histrory?")