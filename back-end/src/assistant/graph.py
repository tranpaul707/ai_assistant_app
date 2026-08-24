from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from typing import Literal

class AgentState(TypedDict):
    query: str
    route : Literal["general", "private"] | None


