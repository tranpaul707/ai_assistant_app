"""Authenticated OAuth initiation and browser/account-bound Gmail callback."""

from __future__ import annotations

import logging
import re
import secrets
from hashlib import sha256
from urllib.parse import urlencode, urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from redis.exceptions import RedisError

from core.auth import AuthenticatedUser, claims_from_id_token
from core.identity import require_identity
from core.settings import FRONTEND_ORIGIN, GOOGLE_REDIRECT_URI, OAUTH_STATE_TTL_SECONDS
from services.gmail.client import authorization_url, exchange_code, persist_credentials
from services.gmail.oauth_state import consume_state, save_state
from services.gmail.token_store import has_gmail_tokens, load_tokens, token_cipher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/gmail", tags=["gmail-auth"])
_BROWSER_COOKIE = "gmail_oauth_browser"


def _sub_from_credentials(creds) -> str | None:
    jwt = getattr(creds, "id_token", None)
    if jwt:
        claims = claims_from_id_token(jwt)
        # An invalid ID token must not fall back to a different identity source.
        return claims["sub"] if claims else None
    token = getattr(creds, "token", None)
    if not token:
        return None
    try:
        response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()
        claims = response.json()
        return require_identity(claims.get("sub")) if isinstance(claims, dict) else None
    except Exception:
        logger.warning("Gmail account identity could not be verified")
        return None


def _redirect_error(reason: str):
    return RedirectResponse(f"{FRONTEND_ORIGIN}/?{urlencode({'gmail': 'error', 'reason': reason})}")


@router.post("/start")
def gmail_start(request: Request, user_sub: AuthenticatedUser):
    # Tokens travel in Authorization only. Returned URL contains random state + PKCE.
    state = secrets.token_urlsafe(32)
    browser_nonce = request.cookies.get(_BROWSER_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", browser_nonce):
        browser_nonce = secrets.token_urlsafe(32)
    try:
        token_cipher()  # Refuse grants if secure credential storage is unconfigured.
        url, verifier = authorization_url(state=state)
        save_state(state, user_sub=user_sub, code_verifier=verifier, browser_nonce=browser_nonce)
    except (RuntimeError, RedisError):
        raise HTTPException(status_code=503, detail="Gmail connection is unavailable") from None
    response = JSONResponse({"authorization_url": url}, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        _BROWSER_COOKIE,
        browser_nonce,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=urlparse(GOOGLE_REDIRECT_URI).scheme == "https",
        samesite="lax",
        path="/auth/gmail",
    )
    return response


@router.get("/callback")
def gmail_callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
):
    if not state:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    try:
        pending = consume_state(state)
    except RedisError:
        raise HTTPException(status_code=503, detail="Gmail connection is unavailable") from None
    browser_nonce = request.cookies.get(_BROWSER_COOKIE, "")
    if (
        not pending
        or not browser_nonce
        or not secrets.compare_digest(
            pending["browser_hash"], sha256(browser_nonce.encode()).hexdigest()
        )
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    # Consume even cancellation/error callbacks; never reflect arbitrary provider text.
    if error:
        return _redirect_error("authorization_denied")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    try:
        creds = exchange_code(code, code_verifier=pending["code_verifier"], state=state)
    except Exception:
        logger.warning("Gmail token exchange failed")
        return _redirect_error("token_exchange_failed")
    actual_sub = _sub_from_credentials(creds)
    if actual_sub is None:
        return _redirect_error("unverified_account")
    if actual_sub != pending["sub"]:
        return _redirect_error("account_mismatch")
    try:
        refresh_token = creds.refresh_token
        if not refresh_token:
            existing = load_tokens(actual_sub) or {}
            refresh_token = existing.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            return _redirect_error("missing_refresh_token")
        persist_credentials(actual_sub, creds, refresh_token=refresh_token)
    except Exception:
        logger.warning("Gmail credential storage failed")
        return _redirect_error("credential_storage_failed")
    return RedirectResponse(f"{FRONTEND_ORIGIN}/?{urlencode({'gmail': 'connected'})}")


@router.get("/status")
def gmail_status(user_sub: AuthenticatedUser):
    try:
        connected = has_gmail_tokens(user_sub)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Gmail connection is unavailable") from None
    return {"authenticated": True, "connected": connected}
