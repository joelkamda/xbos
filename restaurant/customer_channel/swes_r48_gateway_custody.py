"""SWES R48: independently pinned, sealed Gateway checkout credential custody.

Source-only until a genuine PCR-attested signer and WND private key are injected
through an authorized application launcher. Neither an environment flag nor an
HTTP caller can construct the trusted admission or enable default main:app.
No credential value is logged, persisted or returned to the caller.
"""
# ruff: noqa: B008, BLE001 -- FastAPI dependency signatures and uniform fail-closed denial
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.integrations.xafpay_v2.client import XafPayV2Client
from database import get_db

from .gateway_checkout_bridge import VerifiedGatewayMerchantBinding
from .swes_staging_checkout_runtime import (
    TrustedStagingCheckoutAdmission,
    install_staging_checkout_runtime,
)

ENDPOINT = "/internal/swes/r48/staging/gateway-checkout-custody"
SCHEMA = "xafpay.gateway.r48.staging.checkout-custody.v1"
TENANT = 910001
LOCATION = 5
MERCHANT = "4b196022-55a1-548c-b122-f1f9e4b78bea"
GATEWAY_MERCHANT = "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c"
SERVICE = "srv-db3vej67bikc73ai2080"
DB_NAME = "wnd_xafpay_demo_austin_db"
DB_ID = "dpg-db3rd17lk1mc73ckrie0-a"
EXPECTED_BRANCH = "compat/wnd-demo-cc-r1-legacy-neutral-bridge"
GATEWAY = "https://xafpay-gateway-staging.onrender.com"
FLAG = "XAFPAY_R48_WND_GATEWAY_CUSTODY_ENABLED"
SCOPE = ["checkout:create", "checkout:read"]
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TOKEN = re.compile(r"^xps_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
# Nonsecret, durable one-use nonce receipt; raw Gateway bearer is never stored.
_CUSTODY_NONCE_SQL = text("""
    INSERT INTO public.r1_restaurant_commands(
      tenant_id, command_key, request_fingerprint, command_type,
      result_type, result_public_id, completed_at
    ) VALUES(
      910001, :key, :fingerprint, 'gateway_checkout_custody',
      'restricted_gateway_credential', :id, now()
    ) ON CONFLICT(tenant_id, command_key) DO NOTHING
    RETURNING id
""")
_FIELDS = frozenset((
    "schema", "tenant_id", "location_id", "merchant_public_id",
    "gateway_merchant_id", "gateway_source_sha", "wnd_source_sha",
    "credential_id", "nonce", "audience", "scopes", "environment",
    "issued_at_utc", "expires_at_utc", "credential_sha256",
))


class CustodyDenied(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PinnedGatewayCustodyAdmission:
    """Provided only by a protected launcher after independent PCR approval."""
    signer_public_key: ed25519.Ed25519PublicKey
    signer_public_sha256: str
    recipient_private_key: rsa.RSAPrivateKey
    approved_nonce: UUID
    wnd_source_sha: str
    gateway_source_sha: str
    approved_until_utc: datetime

    def validate(self) -> None:
        if not isinstance(self.signer_public_key, ed25519.Ed25519PublicKey):
            raise CustodyDenied()
        if not isinstance(self.recipient_private_key, rsa.RSAPrivateKey):
            raise CustodyDenied()
        if self.recipient_private_key.key_size < 3072:
            raise CustodyDenied()
        if not _SHA.fullmatch(self.signer_public_sha256):
            raise CustodyDenied()
        from cryptography.hazmat.primitives import serialization
        public = self.signer_public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        if not hmac.compare_digest(
            hashlib.sha256(public).hexdigest(), self.signer_public_sha256
        ):
            raise CustodyDenied()
        if not (_COMMIT.fullmatch(self.wnd_source_sha)
                and _COMMIT.fullmatch(self.gateway_source_sha)):
            raise CustodyDenied()
        if not isinstance(self.approved_nonce, UUID) or self.approved_nonce.int == 0:
            raise CustodyDenied()
        if not _utc(self.approved_until_utc):
            raise CustodyDenied()
        now = datetime.now(timezone.utc)
        if not now < self.approved_until_utc <= now + timedelta(hours=2):
            raise CustodyDenied()


def _utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _parse_utc(s: Any) -> datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise CustodyDenied()
    try:
        v = datetime.fromisoformat(s[:-1] + "+00:00")
    except ValueError as exc:
        raise CustodyDenied() from exc
    if not _utc(v):
        raise CustodyDenied()
    return v


def _decode(data: Any) -> bytes:
    if not isinstance(data, str) or len(data) > 4096:
        raise CustodyDenied()
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise CustodyDenied() from exc


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def verify_sealed_gateway_checkout(
    envelope: Mapping[str, Any],
    *,
    admission: PinnedGatewayCustodyAdmission,
    now: datetime,
) -> tuple[str, UUID, str, datetime]:
    """Verify signed issuance authority BEFORE decrypting the raw credential."""
    if not _utc(now) or not isinstance(envelope, dict) or set(envelope) != {
        "header", "ciphertext_b64", "signature_b64"
    }:
        raise CustodyDenied()
    meta = envelope.get("header")
    if not isinstance(meta, dict) or set(meta) != _FIELDS:
        raise CustodyDenied()
    if not (
        meta["schema"] == SCHEMA and type(meta["tenant_id"]) is int
        and meta["tenant_id"] == TENANT
        and type(meta["location_id"]) is int and meta["location_id"] == LOCATION
        and meta["merchant_public_id"] == MERCHANT
        and meta["gateway_merchant_id"] == GATEWAY_MERCHANT
        and meta["gateway_source_sha"] == admission.gateway_source_sha
        and meta["wnd_source_sha"] == admission.wnd_source_sha
        and meta["audience"] == "xafpay-gateway-v2"
        and meta["scopes"] == SCOPE
        and meta["environment"] == "staging"
        and isinstance(meta["credential_sha256"], str)
        and _SHA.fullmatch(meta["credential_sha256"])
    ):
        raise CustodyDenied()
    try:
        cid = UUID(meta["credential_id"])
        nonce = UUID(meta["nonce"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise CustodyDenied() from exc
    if cid.int == 0 or nonce != admission.approved_nonce:
        raise CustodyDenied()
    issued, expires = _parse_utc(meta["issued_at_utc"]), _parse_utc(meta["expires_at_utc"])
    if not (
        issued <= now < expires <= issued + timedelta(minutes=30)
        and now <= issued + timedelta(minutes=2)
        and now < admission.approved_until_utc
    ):
        raise CustodyDenied()
    encrypted, signature = _decode(envelope["ciphertext_b64"]), _decode(envelope["signature_b64"])
    if len(signature) != 64 or len(encrypted) != admission.recipient_private_key.key_size // 8:
        raise CustodyDenied()
    try:
        admission.signer_public_key.verify(signature, _canonical(meta) + b"." + encrypted)
    except InvalidSignature as exc:
        raise CustodyDenied() from exc
    try:
        raw = admission.recipient_private_key.decrypt(
            encrypted, padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(), label=None
            ),
        ).decode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise CustodyDenied() from exc
    if (not _TOKEN.fullmatch(raw) or len(raw) > 256 or
            not hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(),
                                    meta["credential_sha256"])):
        raise CustodyDenied()
    return raw, cid, str(nonce), expires


class ExpiringGatewayCheckoutClient(XafPayV2Client):
    """An expired temporary checkout identity can never initiate a payment."""
    def __init__(self, raw: str, *, expires: datetime):
        super().__init__(GATEWAY, raw)
        self._expires_utc = expires

    def create_checkout(self, request):
        if datetime.now(timezone.utc) >= self._expires_utc:
            raise CustodyDenied()
        return super().create_checkout(request)


def install_signed_gateway_custody_receiver(
    app, *, admission: PinnedGatewayCustodyAdmission | None,
    environ: Mapping[str, str],
) -> bool:
    """Only a separately authenticated launcher may mount this TEST receiver."""
    if environ.get(FLAG) != "1":
        return False
    if not isinstance(admission, PinnedGatewayCustodyAdmission):
        raise CustodyDenied()
    admission.validate()
    expected = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": SERVICE,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
        "RENDER_GIT_BRANCH": EXPECTED_BRANCH,
        "RENDER_GIT_COMMIT": admission.wnd_source_sha,
        "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED": "1",
    }
    if any(environ.get(k) != v for k, v in expected.items()):
        raise CustodyDenied()
    if getattr(app.state, "wnd_gateway_custody_receiver_installed", False):
        raise CustodyDenied()

    router = APIRouter(tags=["SWES private TEST custody"])
    lock = threading.Lock()
    app.state.wnd_gateway_custody_receiver_installed = True

    @router.post(ENDPOINT)
    def accept_protected_checkout(
        request: Request, envelope: dict = Body(...), db=Depends(get_db)
    ):
        try:
            now = datetime.now(timezone.utc)
            raw, credential_id, nonce, expires = verify_sealed_gateway_checkout(
                envelope, admission=admission, now=now
            )
            with lock:
                if getattr(app.state, "wnd_gateway_checkout_runtime", None) is not None:
                    raise CustodyDenied()
                # Verify private hosted DB identity and the original canonical
                # synthetic order BEFORE accepting any credential.
                current = db.execute(text("SELECT current_database()")).scalar_one()
                if current != DB_NAME:
                    raise CustodyDenied()
                valid = db.execute(text("""
                    SELECT count(*)
                    FROM public.r1_restaurant_orders o
                    JOIN public.restaurant_customer_order_drafts d
                     ON d.tenant_id=o.tenant_id AND d.order_public_id=o.public_id
                    JOIN public.pa_merchants m
                     ON m.tenant_id=d.tenant_id AND m.public_id=d.merchant_public_id
                    JOIN public.r1_restaurant_order_lines l
                     ON l.tenant_id=o.tenant_id AND l.order_id=o.id
                    WHERE o.tenant_id=910001
                     AND o.public_id='cba5f76f-73f7-421b-8cce-f8b8823270df'
                     AND o.lifecycle_status='submitted'
                     AND d.location_id=5
                     AND d.merchant_public_id=:merchant
                     AND m.administration_state='registered'
                    GROUP BY o.id HAVING sum(l.quantity*l.unit_price_snapshot)=1000
                     AND min(l.currency)='XAF' AND count(l.id)=1
                """), {"merchant": MERCHANT}).scalar()
                if not valid:
                    raise CustodyDenied()
                digest = hashlib.sha256(
                    _canonical(envelope["header"])
                    + _decode(envelope["ciphertext_b64"])
                ).hexdigest()
                replay = db.execute(_CUSTODY_NONCE_SQL, {
                    "key": "r48:gateway:checkout:" + nonce,
                    "fingerprint": digest,
                    "id": str(credential_id),
                }).scalar()
                if replay is None:
                    raise CustodyDenied()
                # Stage the in-memory trusted client BEFORE committing custody.
                # The one-use nonce must not survive a runtime-admission failure.
                client = ExpiringGatewayCheckoutClient(raw, expires=expires)
                verified_binding = VerifiedGatewayMerchantBinding(
                    tenant_id=TENANT,
                    merchant_public_id=UUID(MERCHANT),
                    gateway_merchant_id=GATEWAY_MERCHANT,
                    service_credential_reference=str(credential_id),
                    verification_state="verified",
                )
                trusted = TrustedStagingCheckoutAdmission(
                    binding=verified_binding,
                    client=client,
                    render_database_id=DB_ID,
                    deployed_source_sha=admission.wnd_source_sha,
                    isolated_synthetic_tenant_proven=True,
                    authenticated_service_checkout_scope_proven=True,
                    sandbox_provider_only_proven=True,
                )
                # Construct on a private, unpublished staging container.
                # A failed install cannot consume the nonce or expose a client
                # to an unrelated checkout request before database commit.
                staging = SimpleNamespace(state=SimpleNamespace())
                installed = install_staging_checkout_runtime(
                    staging, admission=trusted, environ=environ
                )
                staged = getattr(staging.state, "wnd_gateway_checkout_runtime", None)
                if installed is not True or staged is None:
                    raise CustodyDenied()
                db.commit()
                # Publish only AFTER successful durable nonce commit, while
                # retaining the receiver's process-local serialization lock.
                app.state.wnd_gateway_checkout_runtime = staged
            return JSONResponse(status_code=202, content={
                "schema": "xafpay.wnd.r48.checkout-custody-accepted.v1",
                "credential_id": str(credential_id),
                "state": "ACCEPTED",
                "wnd_source_sha": admission.wnd_source_sha,
            })
        except Exception:
            # Never disclose identity, bearer, signature, DB or attestation data.
            db.rollback()
            return JSONResponse(status_code=403, content={"detail": "CUSTODY_NOT_ADMITTED"})

    app.include_router(router)
    return True
