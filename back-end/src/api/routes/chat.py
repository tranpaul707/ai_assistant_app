from fastapi import APIRouter, Header, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from agents.graph import stream_routed
from core.auth import user_sub_from_authorization
from memory.history import messages_for_thread
from memory.threads import get_thread_meta, list_threads, upsert_thread

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "user123"


@router.post("/chat", response_class=EventSourceResponse)
def stream_chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
):
    user_sub = user_sub_from_authorization(authorization)
    upsert_thread(
        request.thread_id,
        title=request.message.strip(),
        user_sub=user_sub,
    )
    for chunk in stream_routed(
        request.message,
        request.thread_id,
        user_sub=user_sub,
    ):
        yield ServerSentEvent(data=chunk, event="token")
    yield ServerSentEvent(raw_data="[DONE]", event="done")


@router.get("/threads")
def get_threads(authorization: str | None = Header(default=None)):
    user_sub = user_sub_from_authorization(authorization)
    return {"threads": list_threads(user_sub)}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, authorization: str | None = Header(default=None)):
    user_sub = user_sub_from_authorization(authorization)
    meta = get_thread_meta(thread_id)
    if meta is None:
        # Allow loading if checkpoint exists even without registry row.
        messages = messages_for_thread(thread_id)
        if not messages:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {"thread_id": thread_id, "title": "Chat", "messages": messages}

    owner = meta.get("user_sub")
    if owner and user_sub and owner != user_sub:
        raise HTTPException(status_code=403, detail="Thread not accessible")

    return {
        "thread_id": thread_id,
        "title": meta.get("title", "Chat"),
        "messages": messages_for_thread(thread_id),
    }
