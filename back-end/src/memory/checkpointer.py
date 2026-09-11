from functools import lru_cache

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.redis import RedisSaver

from core.settings import REDIS_URI


@lru_cache(maxsize=1)
def get_checkpointer() -> RedisSaver:
    """Return a shared Redis checkpointer for this process."""
    checkpointer = RedisSaver(redis_url=REDIS_URI)
    checkpointer.setup()
    return checkpointer


def thread_config(
    thread_id: str,
    *,
    user_sub: str | None = None,
) -> RunnableConfig:
    """Build RunnableConfig for a conversation thread.

    `thread_id` is the conversation UUID. `user_sub` is Google identity for tools.
    """
    configurable: dict = {"thread_id": thread_id}
    if user_sub:
        configurable["user_sub"] = user_sub
    return {"configurable": configurable}
