from __future__ import annotations

import hashlib
import hmac
import os
import re

from .contracts import H1BError, TOKEN_DIGEST_CURRENT_ENV, TOKEN_DIGEST_NEXT_ENV

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _configured_digest(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    selected = value.strip().lower()
    if selected.startswith("sha256:"):
        selected = selected[7:]
    if not _DIGEST.fullmatch(selected):
        return None
    return selected


def authenticate_bearer_value(raw_token: str | None, *, correlation_ref: str | None = None) -> str:
    """Verify an opaque credential against current/next SHA-256 digests."""
    if raw_token is None or not raw_token:
        raise H1BError("SERVICE_AUTH_REQUIRED", correlation_ref=correlation_ref)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    current = _configured_digest(TOKEN_DIGEST_CURRENT_ENV)
    nxt = _configured_digest(TOKEN_DIGEST_NEXT_ENV)
    if current and hmac.compare_digest(digest, current):
        return "current"
    if nxt and hmac.compare_digest(digest, nxt):
        return "next"
    raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=correlation_ref)


def bearer_from_authorization_header(value: str | None, *, correlation_ref: str | None = None) -> str:
    if not value:
        raise H1BError("SERVICE_AUTH_REQUIRED", correlation_ref=correlation_ref)
    prefix = "Bearer "
    if not value.startswith(prefix):
        raise H1BError("SERVICE_AUTH_REQUIRED", correlation_ref=correlation_ref)
    token = value[len(prefix):]
    if not token or token != token.strip():
        raise H1BError("SERVICE_AUTH_REQUIRED", correlation_ref=correlation_ref)
    return token
