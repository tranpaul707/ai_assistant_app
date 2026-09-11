"""Gmail API client — search and fetch messages for the authenticated user."""

from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Google often returns alias scopes (email/profile) in addition to the ones we
# request; without this, fetch_token raises and the callback never persists.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from core.settings import (
    GMAIL_SCOPES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from services.gmail.models import Email
from services.gmail.token_store import load_tokens, save_tokens

logger = logging.getLogger(__name__)


def _flow() -> Flow:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise RuntimeError(
            "Gmail OAuth is not configured. Create back-end/.env with "
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (Web application client "
            "from Google Cloud Console), then restart uvicorn."
        )
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=GMAIL_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


def authorization_url(*, login_hint: str | None = None, state: str | None = None) -> tuple[str, str]:
    """Return (authorize_url, code_verifier). Verifier is required for token exchange (PKCE)."""
    flow = _flow()
    kwargs: dict[str, Any] = {
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    if login_hint:
        kwargs["login_hint"] = login_hint
    if state:
        kwargs["state"] = state
    url, _ = flow.authorization_url(**kwargs)
    verifier = flow.code_verifier
    if not verifier:
        raise RuntimeError("OAuth PKCE code_verifier was not generated")
    return url, verifier


def exchange_code(code: str, *, code_verifier: str | None = None) -> Credentials:
    flow = _flow()
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_for_user(sub: str) -> Credentials | None:
    data = load_tokens(sub)
    if not data or not data.get("refresh_token"):
        return None
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=data.get("scopes") or GMAIL_SCOPES,
    )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            persist_credentials(sub, creds)
        else:
            return None
    return creds


def persist_credentials(sub: str, creds: Credentials) -> None:
    save_tokens(
        sub,
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "scopes": list(creds.scopes or GMAIL_SCOPES),
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        },
    )


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {h.get("name", "").lower(): h.get("value", "") for h in headers}


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, Any], collected: list[tuple[str, str]]) -> None:
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/"):
        collected.append((mime, _decode_body_data(data)))
    for part in payload.get("parts") or []:
        _walk_parts(part, collected)


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_body(payload: dict[str, Any]) -> str:
    collected: list[tuple[str, str]] = []
    _walk_parts(payload, collected)
    plain = [t for m, t in collected if m == "text/plain" and t.strip()]
    if plain:
        return plain[0].strip()
    html = [t for m, t in collected if m == "text/html" and t.strip()]
    if html:
        return _strip_html(html[0])
    # Single-part body
    data = (payload.get("body") or {}).get("data")
    if data:
        raw = _decode_body_data(data)
        if (payload.get("mimeType") or "").startswith("text/html"):
            return _strip_html(raw)
        return raw.strip()
    return ""


def _parse_recipients(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _message_to_email(raw: dict[str, Any]) -> Email:
    payload = raw.get("payload") or {}
    headers = _header_map(payload)
    subject = headers.get("subject") or "(no subject)"
    sender = headers.get("from") or ""
    recipients = _parse_recipients(headers.get("to") or "")
    received_at = None
    date_hdr = headers.get("date")
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = None
    if received_at is None and raw.get("internalDate"):
        try:
            ms = int(raw["internalDate"])
            received_at = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        except Exception:
            pass

    body = extract_body(payload)
    preview = (raw.get("snippet") or body[:200]).strip()
    return Email(
        id=raw["id"],
        thread_id=raw.get("threadId") or "",
        subject=subject,
        sender=sender,
        recipients=recipients,
        received_at=received_at,
        body=body,
        preview=preview,
    )


def search_emails(sub: str, query: str, *, max_results: int = 15) -> list[Email]:
    creds = credentials_for_user(sub)
    if creds is None:
        raise PermissionError("Gmail is not authorized for this user")

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    message_refs = listed.get("messages") or []
    emails: list[Email] = []
    for ref in message_refs:
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=ref["id"], format="full")
            .execute()
        )
        emails.append(_message_to_email(raw))
    return emails
