# Run from back-end/src:
#   uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api.routes import chat, upload


app = FastAPI()

# Explicit common Vite origins + regex for any localhost / 127.0.0.1 port
# (Cursor preview, alternate Vite ports, etc. otherwise get CORS 400 on OPTIONS).
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(upload.router)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
