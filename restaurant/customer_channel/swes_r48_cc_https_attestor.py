"""R48 server-owned WND->CC authenticated HTTPS receipt and sender attestation.

No route installation or credential provisioning. Default-off via absent secrets.
"""
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .swes_r48_cc_attestation_verifier import verify_attestation_response
from .swes_r48_cc_event_validation import CCEventRejected

CC_HOST = "xafpay-customer-channel-staging.onrender.com"
CC_PATH = "/internal/swes/track-a/test-only/receipt-attestations"

async def attest_cc_signed_sender(proof, payload: dict) -> bool:
    """Trust only a pinned HTTPS response to a WND-authenticated CC request."""
    base = os.environ.get("XAFPAY_R48_CC_ATTEST_BASE_URL", "").rstrip("/")
    bearer = os.environ.get("XAFPAY_R48_WND_TO_CC_ATTEST_BEARER", "")
    url = urlparse(base)
    if (url.scheme != "https" or url.username or url.password or url.query
        or url.fragment or url.path not in ("", "/")
        or not url.hostname or url.port is not None
        or url.hostname != CC_HOST
        or len(bearer) < 32 or len(bearer) > 256
        or any(ord(ch) < 33 or ord(ch) > 126 for ch in bearer)):
        raise CCEventRejected("CC_ATTESTATION_NOT_CONFIGURED")
    if datetime.now(timezone.utc) >= proof.expires_at:
        raise CCEventRejected("CC_ATTESTATION_EXPIRED")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                base + CC_PATH, json=payload,
                headers={"Authorization": "Bearer " + bearer,
                         "Accept": "application/json"},
            )
        if response.status_code != 200 or "application/json" not in response.headers.get("content-type", ""):
            raise CCEventRejected("CC_ATTESTATION_DENIED")
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CCEventRejected("CC_ATTESTATION_UNAVAILABLE") from exc
    return verify_attestation_response(
        payload, data, transport_authenticated=True,
    )
