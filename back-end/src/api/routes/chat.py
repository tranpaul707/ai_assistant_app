"""Authenticated chat and conversation history routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, field_validator

from agents.graph import stream_routed
from core.auth import AuthenticatedUser
from core.identity import validate_thread_id
from memory.history import messages_for_thread
from memory.threads import get_thread_meta, list_threads, upsert_thread

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    thread_id: str

    @field_validator("thread_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_thread_id(value)


def authorize_chat(request: ChatRequest, user_sub: AuthenticatedUser) -> str:
    # Check authentication and ownership before sending streaming headers.
    try:
        upsert_thread(request.thread_id, title=request.message.strip(), user_sub=user_sub)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Thread not found") from exc
    return user_sub


@router.post("/chat", response_class=EventSourceResponse)
def stream_chat(request: ChatRequest, user_sub: Annotated[str, Depends(authorize_chat)]):
    for chunk in stream_routed(request.message, request.thread_id, user_sub=user_sub):
        yield ServerSentEvent(data=chunk, event="token")
    yield ServerSentEvent(raw_data="[DONE]", event="done")


@router.get("/threads")
def get_threads(user_sub: AuthenticatedUser):
    return {"threads": list_threads(user_sub)}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, user_sub: AuthenticatedUser):
    try:
        validate_thread_id(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid thread ID") from exc
    meta = get_thread_meta(thread_id, user_sub=user_sub)
    if meta is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {
        "thread_id": thread_id,
        "title": meta.get("title", "Chat"),
        "messages": messages_for_thread(thread_id, user_sub=user_sub),
    }
