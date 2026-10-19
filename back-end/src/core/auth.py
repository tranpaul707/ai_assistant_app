"""Fail-closed Google ID token verification and shared API authentication."""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from core.settings import GOOGLE_CLIENT_ID
from core.identity import require_identity

logger = logging.getLogger(__name__)


def verify_google_id_token(token: str) -> dict[str, Any] | None:
    """Verify signature, issuer, audience, lifetime and required claim shapes."""
    if not isinstance(token, str) or not token or not GOOGLE_CLIENT_ID:
        return None
    try:
        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=0,
        )
        if not isinstance(claims, dict):
            return None
        if claims.get("aud") != GOOGLE_CLIENT_ID or claims.get("iss") not in (
            "accounts.google.com",
            "https://accounts.google.com",
        ):
            return None
        require_identity(claims.get("sub"))
        issued, expiry = claims.get("iat"), claims.get("exp")
        if (
            not isinstance(issued, int)
            or isinstance(issued, bool)
            or not isinstance(expiry, int)
            or isinstance(expiry, bool)
        ):
            return None
        now = time.time()
        if issued > now or expiry <= now or expiry <= issued:
            return None
        return claims
    except Exception:
        # Verification exceptions can contain rejected tokens or claim values.
        logger.warning("Google ID token verification failed")
        return None


def claims_from_id_token(token: str) -> dict[str, Any] | None:
    """Return verified claims only; there is no unsigned or anonymous fallback."""
    return verify_google_id_token(token)


def user_sub_from_authorization(authorization: str | None) -> str | None:
    """Extract Google `sub` from an Authorization: Bearer <id_token> header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    claims = claims_from_id_token(parts[1].strip())
    if not claims:
        return None
    return claims["sub"]


def require_user_sub(authorization: str | None = Header(default=None)) -> str:
    """One dependency for every private API route, with consistent 401 responses."""
    sub = user_sub_from_authorization(authorization)
    if sub is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sub


AuthenticatedUser = Annotated[str, Depends(require_user_sub)]
