from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.redis import RedisSaver

REDIS_URI = "redis://localhost:6379"

_checkpointer: RedisSaver | None = None


def get_checkpointer() -> RedisSaver:
    """Return a process-wide Redis checkpointer (created once)."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = RedisSaver(redis_url=REDIS_URI)
        _checkpointer.setup()
    return _checkpointer


def thread_config(thread_id: str) -> RunnableConfig:
    """Build the RunnableConfig used to continue a conversation thread."""
    return {"configurable": {"thread_id": thread_id}}
