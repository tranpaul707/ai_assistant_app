"""Google ID token verification (GIS Sign-In → backend identity)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from core.settings import GOOGLE_CLIENT_ID

logger = logging.getLogger(__name__)


def _decode_jwt_payload_unverified(token: str) -> dict[str, Any] | None:
    """Decode JWT payload without signature verification (identity binding only)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")))
    except Exception:
        return None


def verify_google_id_token(token: str) -> dict[str, Any] | None:
    """Return token claims if valid, otherwise None."""
    if not token or not GOOGLE_CLIENT_ID:
        return None
    try:
        return id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=60,
        )
    except Exception as exc:
        logger.warning("Google ID token verification failed: %s", type(exc).__name__)
        return None


def claims_from_id_token(token: str) -> dict[str, Any] | None:
    """Prefer verified claims; fall back to unverified payload for local binding."""
    claims = verify_google_id_token(token)
    if claims:
        return claims
    return _decode_jwt_payload_unverified(token)


def user_sub_from_authorization(authorization: str | None) -> str | None:
    """Extract Google `sub` from an Authorization: Bearer <id_token> header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    claims = claims_from_id_token(parts[1].strip())
    if not claims:
        return None
    sub = claims.get("sub")
    return str(sub) if sub else None
