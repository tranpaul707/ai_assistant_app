from fastapi import APIRouter
from pydantic import BaseModel
from assistant.assistant import handle_query
from fastapi.sse import EventSourceResponse, ServerSentEvent

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/chat", response_class=EventSourceResponse)
def stream_chat(request: ChatRequest):
    for chunk in handle_query(request.message):
        yield ServerSentEvent(data=chunk, event="token")
    yield ServerSentEvent(raw_data="[DONE]", event="done")