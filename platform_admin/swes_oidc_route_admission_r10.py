"""Exact-path, GET-only public browser handshake admission.

This function is intentionally narrower than general /internal or /auth bypass.
It cannot confer identity, authorization, owner binding or PC5 session access.
The route must be explicitly registered and SWES_OIDC_ENABLED separately turned
on after the WND/PCR deployment gates; 'registered' alone never enables login.
"""
from __future__ import annotations

import os

_PUBLIC_OIDC_GET_PATHS = frozenset((
    "/internal/swes/pa/oidc/start",
    "/internal/swes/pa/oidc/callback",
))


def is_public_oidc_handshake(path: str, method: str) -> bool:
    return (
        os.getenv("SWES_OIDC_ROUTE_REGISTERED") == "true"
        and method == "GET"
        and isinstance(path, str)
        and path in _PUBLIC_OIDC_GET_PATHS
    )
