"""Gmail API client — search and fetch messages for the authenticated user."""

from __future__ import annotations

import base64
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from html import unescape
from functools import partial
from typing import Any

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google often returns alias scopes (email/profile) in addition to the ones we
# request; without this, fetch_token raises and the callback never persists.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from core.settings import (
    GMAIL_SCOPES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from services.gmail.models import Attachment, Email, EmailSummary, EmailThread, SearchPage
from services.gmail.query import email_matches_people
from services.gmail.token_store import load_tokens, save_tokens

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 50
MAX_PAGES = 5
MAX_BODY_CHARS = 6000
MAX_THREAD_MESSAGES = 10
_HEADERS = ["From", "To", "Cc", "Subject", "Date", "List-Id", "Auto-Submitted"]
_METADATA_FIELDS = "id,threadId,labelIds,snippet,internalDate,payload/headers"


def _flow(*, state: str | None = None, code_verifier: str | None = None) -> Flow:
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
        state=state,
        code_verifier=code_verifier,
    )


def authorization_url(
    *, login_hint: str | None = None, state: str | None = None
) -> tuple[str, str]:
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


def exchange_code(code: str, *, code_verifier: str, state: str) -> Credentials:
    if not code_verifier or not state:
        raise ValueError("OAuth state and PKCE verifier are required")
    flow = _flow(state=state, code_verifier=code_verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not isinstance(credentials, Credentials):
        raise ValueError("Unexpected OAuth credential type")
    return credentials


def credentials_for_user(sub: str) -> Credentials | None:
    data = load_tokens(sub)
    if not data or not data.get("refresh_token"):
        return None
    expiry = None
    if data.get("expiry"):
        try:
            parsed = datetime.fromisoformat(data["expiry"].replace("Z", "+00:00"))
            # google-auth compares against a naive UTC clock.
            expiry = (
                parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
            )
        except (ValueError, TypeError):
            pass
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=data.get("scopes") or GMAIL_SCOPES,
        expiry=expiry,
    )
    if expiry is None or not creds.valid:
        try:
            creds.refresh(partial(Request(), timeout=20))
            persist_credentials(sub, creds)
        except Exception:
            logger.warning("Gmail credential refresh failed; reconnect required")
            return None
    return creds


def persist_credentials(
    sub: str,
    creds: Credentials,
    *,
    refresh_token: str | None = None,
) -> None:
    refresh_token = creds.refresh_token or refresh_token
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("A refresh token is required")
    save_tokens(
        sub,
        {
            "token": creds.token,
            "refresh_token": refresh_token,
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
    # A text attachment is not the message body.
    if payload.get("filename"):
        return
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
    return unescape(text).strip()


def extract_body(payload: dict[str, Any]) -> str:
    collected: list[tuple[str, str]] = []
    _walk_parts(payload, collected)
    plain = [t for m, t in collected if m == "text/plain" and t.strip()]
    if plain:
        return plain[0].strip()
    html = [t for m, t in collected if m == "text/html" and t.strip()]
    if html:
        return _strip_html(html[0])
    return ""


def _parse_recipients(value: str) -> list[str]:
    if not value:
        return []
    return [formataddr((name, address)) for name, address in getaddresses([value]) if address]


def _message_to_summary(raw: dict[str, Any]) -> EmailSummary:
    payload = raw.get("payload") or {}
    headers = _header_map(payload)
    subject = headers.get("subject") or "(no subject)"
    sender = headers.get("from") or ""
    recipients = _parse_recipients(headers.get("to") or "")
    received_at = None
    date_hdr = headers.get("date")
    internal_date_ms = None
    if raw.get("internalDate") is not None:
        try:
            internal_date_ms = int(raw["internalDate"])
            received_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError, OSError):
            internal_date_ms = None
    if received_at is None and date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            received_at = None
    return EmailSummary(
        id=raw["id"],
        thread_id=raw.get("threadId") or "",
        subject=subject[:500],
        sender=sender[:500],
        recipients=[value[:500] for value in recipients[:20]],
        received_at=received_at,
        preview=(raw.get("snippet") or "").strip()[:500],
        internal_date_ms=internal_date_ms,
        date_header=(date_hdr or "")[:100],
        cc=_parse_recipients(headers.get("cc") or "")[:20],
        labels=(raw.get("labelIds") or [])[:30],
        list_id=(headers.get("list-id") or "")[:300],
        auto_submitted=(headers.get("auto-submitted") or "")[:100],
    )


def _attachments(payload: dict[str, Any]) -> list[Attachment]:
    result = []
    if payload.get("filename"):
        body = payload.get("body") or {}
        result.append(
            Attachment(
                filename=payload["filename"][:300],
                mime_type=payload.get("mimeType") or "",
                size=int(body.get("size") or 0),
                attachment_id=body.get("attachmentId") or "",
            )
        )
    for part in payload.get("parts") or []:
        result.extend(_attachments(part))
    return result[:20]


def _message_to_email(raw: dict[str, Any]) -> Email:
    summary = _message_to_summary(raw)
    body = extract_body(raw.get("payload") or {})
    return Email(
        **asdict(summary),
        body=body[:MAX_BODY_CHARS],
        attachments=_attachments(raw.get("payload") or {}),
        body_truncated=len(body) > MAX_BODY_CHARS,
    )


def _service(sub: str):
    creds = credentials_for_user(sub)
    if creds is None:
        raise PermissionError("Gmail is not authorized for this user")
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=20))
    return build("gmail", "v1", http=http, cache_discovery=False)


def _execute(request):
    """One bounded retry for transient Google API failures."""
    return request.execute(num_retries=1)


def _error(exc: Exception, message_id: str = "") -> dict[str, str]:
    status = getattr(getattr(exc, "resp", None), "status", None)
    code = "not_found" if status == 404 else "api_error"
    return {"id": message_id, "code": code}


def _check_access_error(exc: Exception) -> None:
    if isinstance(exc, HttpError) and exc.resp.status in (401, 403):
        raise PermissionError("Gmail access denied; reconnect required") from None


def _validate_id(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid Gmail message or thread ID")


def chronological_key(email: EmailSummary) -> float:
    return email.received_at.timestamp() if email.received_at else float("-inf")


def search_emails(
    sub: str,
    query: str,
    *,
    max_results: int = 10,
    page_token: str = "",
    sender_filter: str = "",
    to_filter: str = "",
) -> SearchPage:
    """Search metadata only. Refill after people filtering under a fixed scan budget."""
    if not 1 <= max_results <= MAX_CANDIDATES:
        raise ValueError("max_results must be between 1 and 50")
    if not query.strip() or len(query) > 2048 or len(page_token) > 2048:
        raise ValueError("Invalid Gmail query or page token")
    service = _service(sub)
    messages = service.users().messages()
    result = SearchPage()
    token = page_token
    seen_ids: set[str] = set()
    seen_tokens: set[str] = set()
    while result.pages_fetched < MAX_PAGES and result.scanned_count < MAX_CANDIDATES:
        size = min(max_results - len(result.messages), MAX_CANDIDATES - result.scanned_count)
        kwargs = {"userId": "me", "q": query, "maxResults": size}
        if token:
            kwargs["pageToken"] = token
        try:
            listed = _execute(messages.list(**kwargs))
        except Exception as exc:
            _check_access_error(exc)
            if not result.pages_fetched:
                raise
            result.errors.append(_error(exc))
            result.next_page_token = token or None
            break
        result.pages_fetched += 1
        for ref in listed.get("messages") or []:
            result.scanned_count += 1
            message_id = ref.get("id") or ""
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            try:
                raw = _execute(
                    messages.get(
                        userId="me",
                        id=message_id,
                        format="metadata",
                        metadataHeaders=_HEADERS,
                        fields=_METADATA_FIELDS,
                    )
                )
                email = _message_to_summary(raw)
                if email_matches_people(
                    sender_header=email.sender,
                    recipients=email.recipients,
                    sender_filter=sender_filter,
                    to_filter=to_filter,
                ):
                    result.messages.append(email)
            except Exception as exc:
                _check_access_error(exc)
                result.errors.append(_error(exc, message_id))
        token = listed.get("nextPageToken") or ""
        result.next_page_token = token or None
        if not token or len(result.messages) >= max_results:
            break
        if token in seen_tokens:
            result.errors.append({"id": "", "code": "repeated_page_token"})
            break
        seen_tokens.add(token)
    result.messages.sort(key=chronological_key, reverse=True)
    return result


def _read_email(service, message_id: str) -> Email:
    _validate_id(message_id)
    try:
        raw = _execute(service.users().messages().get(userId="me", id=message_id, format="full"))
    except Exception as exc:
        _check_access_error(exc)
        raise
    return _message_to_email(raw)


def read_email(sub: str, message_id: str) -> Email:
    """Read one chosen message, only from this user's authorized mailbox."""
    _validate_id(message_id)
    return _read_email(_service(sub), message_id)


def read_email_thread(sub: str, thread_id: str, *, max_messages: int = 5) -> EmailThread:
    """Read metadata for one thread, then full bodies only for its latest N messages."""
    _validate_id(thread_id)
    if not 1 <= max_messages <= MAX_THREAD_MESSAGES:
        raise ValueError("max_messages must be between 1 and 10")
    service = _service(sub)
    try:
        raw = _execute(
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=_HEADERS,
                fields=f"id,messages({_METADATA_FIELDS})",
            )
        )
    except Exception as exc:
        _check_access_error(exc)
        raise
    candidates = [_message_to_summary(message) for message in raw.get("messages") or []]
    result = EmailThread(
        id=thread_id, total_messages=len(candidates), truncated=len(candidates) > max_messages
    )
    # Most recent N, presented oldest-to-newest for conversation comprehension.
    selected = sorted(candidates, key=chronological_key, reverse=True)[:max_messages]
    for candidate in reversed(selected):
        try:
            result.messages.append(_read_email(service, candidate.id))
        except Exception as exc:
            _check_access_error(exc)
            result.errors.append(_error(exc, candidate.id))
    result.messages.sort(key=chronological_key)
    return result
