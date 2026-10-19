from functools import lru_cache

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.redis import RedisSaver

from core.settings import REDIS_URI
from core.identity import owner_namespace, validate_thread_id


@lru_cache(maxsize=1)
def get_checkpointer() -> RedisSaver:
    """Return a shared Redis checkpointer for this process."""
    checkpointer = RedisSaver(redis_url=REDIS_URI)
    checkpointer.setup()
    return checkpointer


def thread_config(
    thread_id: str,
    *,
    user_sub: str,
) -> RunnableConfig:
    """Build RunnableConfig for a conversation thread.

    Active checkpoints never use the old, globally shared thread ID namespace.
    """
    configurable: dict = {
        "thread_id": f"v2_{owner_namespace(user_sub)}_{validate_thread_id(thread_id)}",
        "user_sub": user_sub,
    }
    return {"configurable": configurable}
