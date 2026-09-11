from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse

from core.auth import claims_from_id_token, user_sub_from_authorization
from core.settings import FRONTEND_ORIGIN
from services.gmail.client import authorization_url, exchange_code, persist_credentials
from services.gmail.token_store import has_gmail_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/gmail", tags=["gmail-auth"])

# Short-lived OAuth state → {sub, code_verifier}. In-memory is enough for local.
_pending_states: dict[str, dict[str, str]] = {}


def _sub_from_credentials(creds) -> str | None:
    id_token_jwt = getattr(creds, "id_token", None)
    if id_token_jwt:
        claims = claims_from_id_token(id_token_jwt)
        if claims and claims.get("sub"):
            return str(claims["sub"])

    # Fall back to userinfo with the access token.
    token = getattr(creds, "token", None)
    if not token:
        return None
    try:
        response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if response.ok:
            sub = response.json().get("sub")
            return str(sub) if sub else None
    except Exception:
        logger.exception("Failed to resolve Google sub via userinfo")
    return None


@router.get("/start")
def gmail_start(
    login_hint: str | None = Query(default=None),
    id_token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    """Begin Gmail OAuth.

    Browser navigation cannot send Authorization headers, so the frontend also
    passes the GIS id_token as a query param to bind the OAuth result to `sub`.
    """
    sub = user_sub_from_authorization(authorization)
    hint = login_hint

    if id_token:
        claims = claims_from_id_token(id_token)
        if claims:
            sub = sub or (str(claims["sub"]) if claims.get("sub") else None)
            hint = hint or claims.get("email")

    if not hint and authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2:
            claims = claims_from_id_token(parts[1].strip())
            if claims:
                hint = claims.get("email")
                sub = sub or (str(claims["sub"]) if claims.get("sub") else None)

    if not sub:
        raise HTTPException(
            status_code=401,
            detail="Sign in with Google first, then connect Gmail.",
        )

    state = secrets.token_urlsafe(24)
    try:
        url, code_verifier = authorization_url(login_hint=hint, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _pending_states[state] = {"sub": sub, "code_verifier": code_verifier}
    return RedirectResponse(url)


@router.get("/callback")
def gmail_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        qs = urlencode({"gmail": "error", "reason": error})
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?{qs}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    pending = _pending_states.pop(state, None) or {}
    expected_sub = pending.get("sub")
    code_verifier = pending.get("code_verifier")
    try:
        creds = exchange_code(code, code_verifier=code_verifier)
    except Exception:
        logger.exception("Gmail token exchange failed")
        qs = urlencode({"gmail": "error", "reason": "token_exchange_failed"})
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?{qs}")

    sub = expected_sub or _sub_from_credentials(creds)

    if not sub:
        qs = urlencode({"gmail": "error", "reason": "missing_user"})
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?{qs}")

    if not creds.refresh_token:
        from services.gmail.token_store import load_tokens

        existing = load_tokens(sub) or {}
        if existing.get("refresh_token"):
            creds.refresh_token = existing["refresh_token"]

    if not creds.refresh_token:
        qs = urlencode({"gmail": "error", "reason": "missing_refresh_token"})
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?{qs}")

    persist_credentials(sub, creds)
    logger.info("Gmail tokens saved for sub ending ...%s", sub[-6:])
    qs = urlencode({"gmail": "connected"})
    return RedirectResponse(f"{FRONTEND_ORIGIN}/?{qs}")


@router.get("/status")
def gmail_status(authorization: str | None = Header(default=None)):
    sub = user_sub_from_authorization(authorization)
    if not sub:
        return {"connected": False, "authenticated": False}
    return {
        "authenticated": True,
        "connected": has_gmail_tokens(sub),
        "sub": sub,
    }
