from functools import lru_cache

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.redis import RedisSaver

REDIS_URI = "redis://localhost:6379"


@lru_cache(maxsize=1)
def get_checkpointer() -> RedisSaver:
    """Return a shared Redis checkpointer for this process."""
    checkpointer = RedisSaver(redis_url=REDIS_URI)
    checkpointer.setup()
    return checkpointer


def thread_config(thread_id: str) -> RunnableConfig:
    """Build the RunnableConfig used to continue a conversation thread."""
    return {"configurable": {"thread_id": thread_id}}
