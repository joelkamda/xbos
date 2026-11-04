"""R48 TEST-only mutual-authenticated readiness proof for WND Gateway custody.

Gateway signs a fresh, exact-scope request using the same independently pinned
Ed25519 signer that signs credential deliveries. WND proves possession of its
independently approved RSA-OAEP recipient private key by signing the challenge
with RSA-PSS. Nothing here authorizes Gateway credential issuance by itself.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .swes_r48_gateway_custody import (
    CustodyDenied,
    PinnedGatewayCustodyAdmission,
    _canonical,
    _decode,
    _parse_utc,
    _utc,
)

REQUEST_SCHEMA = "xafpay.gateway.r48.staging.custody-ready-request.v1"
PROOF_SCHEMA = "xafpay.wnd.r48.staging.custody-ready-proof.v1"
PATH = "/internal/swes/r48/staging/gateway-checkout-custody/ready"
_REQUEST_CONTEXT = b"xafpay:gateway:r48:staging:readiness-request:v1\x00"
_PROOF_CONTEXT = b"xafpay:wnd:r48:staging:readiness-proof:v1\x00"
_REQUEST_FIELDS = frozenset({
    "schema", "nonce", "challenge_b64", "issued_at_utc",
    "tenant_id", "location_id", "merchant_public_id", "gateway_merchant_id",
    "wnd_source_sha", "gateway_source_sha", "audience", "environment",
})
_PROOF_FIELDS = frozenset({
    "schema", "nonce", "challenge_b64", "issued_at_utc", "expires_at_utc",
    "recipient_key_sha256", "merchant_public_id", "gateway_merchant_id",
    "wnd_source_sha", "gateway_source_sha", "audience", "environment",
})


def recipient_public_spki(admission: PinnedGatewayCustodyAdmission) -> bytes:
    return admission.recipient_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def sign_readiness_proof(
    request: dict[str, Any],
    *,
    signature_b64: str,
    admission: PinnedGatewayCustodyAdmission,
    now: datetime,
) -> dict[str, Any]:
    """A signed, expiry-bound statement by the real WND custody RSA key."""
    if (
        not _utc(now) or not isinstance(request, dict)
        or set(request) != _REQUEST_FIELDS
        or type(request.get("tenant_id")) is not int
        or request["tenant_id"] != 910001
        or type(request.get("location_id")) is not int
        or request["location_id"] != 5
        or request.get("schema") != REQUEST_SCHEMA
        or request.get("merchant_public_id") != "4b196022-55a1-548c-b122-f1f9e4b78bea"
        or request.get("gateway_merchant_id") != "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c"
        or request.get("wnd_source_sha") != admission.wnd_source_sha
        or request.get("gateway_source_sha") != admission.gateway_source_sha
        or request.get("audience") != "xafpay-gateway-v2"
        or request.get("environment") != "staging"
    ):
        raise CustodyDenied()

    try:
        nonce = UUID(request["nonce"])
        challenge = _decode(request["challenge_b64"])
        signature = _decode(signature_b64)
    except (TypeError, ValueError, AttributeError) as exc:
        raise CustodyDenied() from exc
    if (
        nonce != admission.approved_nonce or len(challenge) != 32
        or len(signature) != 64 or not _utc(admission.approved_until_utc)
        or now >= admission.approved_until_utc
    ):
        raise CustodyDenied()
    issued = _parse_utc(request["issued_at_utc"])
    if not (issued <= now < issued + timedelta(seconds=45)):
        raise CustodyDenied()

    try:
        admission.signer_public_key.verify(
            signature, _REQUEST_CONTEXT + _canonical(request)
        )
    except InvalidSignature as exc:
        raise CustodyDenied() from exc

    expires = min(now + timedelta(seconds=30), admission.approved_until_utc)
    proof = {
        "schema": PROOF_SCHEMA,
        "nonce": request["nonce"],
        "challenge_b64": request["challenge_b64"],
        "issued_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": expires.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "recipient_key_sha256": hashlib.sha256(recipient_public_spki(admission)).hexdigest(),
        "merchant_public_id": request["merchant_public_id"],
        "gateway_merchant_id": request["gateway_merchant_id"],
        "wnd_source_sha": admission.wnd_source_sha,
        "gateway_source_sha": admission.gateway_source_sha,
        "audience": request["audience"],
        "environment": request["environment"],
    }
    if set(proof) != _PROOF_FIELDS:
        raise CustodyDenied()
    signed = admission.recipient_private_key.sign(
        _PROOF_CONTEXT + _canonical(proof),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return {
        "proof": proof,
        "signature_b64": base64.b64encode(signed).decode("ascii"),
    }
