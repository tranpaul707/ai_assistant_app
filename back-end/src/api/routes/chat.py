from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from assistant.graph import stream_routed

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "user123"


@router.post("/chat", response_class=EventSourceResponse)
def stream_chat(request: ChatRequest):
    for chunk in stream_routed(request.message, request.thread_id):
        yield ServerSentEvent(data=chunk, event="token")
    yield ServerSentEvent(raw_data="[DONE]", event="done")
