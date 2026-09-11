# Run from back-end/src:
#   uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api.routes import auth_gmail, chat, upload
from core.settings import FRONTEND_ORIGIN


app = FastAPI()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    FRONTEND_ORIGIN,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(origins)),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(auth_gmail.router)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
