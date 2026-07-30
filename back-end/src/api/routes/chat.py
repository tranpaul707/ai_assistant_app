from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/chat")
def chat(request: ChatRequest):
    return {"message": request.message}