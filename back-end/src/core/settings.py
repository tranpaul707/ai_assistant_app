"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load back-end/.env then repo-root .env (later files do not override earlier).
_BACK_END_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACK_END_ROOT.parent
load_dotenv(_BACK_END_ROOT / ".env")
load_dotenv(_REPO_ROOT / ".env")

REDIS_URI = os.getenv("REDIS_URI", "redis://localhost:6379")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://127.0.0.1:8000/auth/gmail/callback",
)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

DATA_DIR = _BACK_END_ROOT / "data"
OAUTH_DIR = DATA_DIR / "oauth"

GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]
