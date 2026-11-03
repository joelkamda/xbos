"""Independent TEST-only Track A CC→WND first IA0 receiver.

NOT the protected R48 V2 receiver: no release-fence substitution, no epoch
activation, no payment or order creation. Admits only a real, first, signed CC
receipt independently attested over pinned HTTPS and a distinct PC5 service
principal. Normal main:app publishes NO route unless the TEST flag is enabled.
"""
# ruff: noqa: B008 - standard FastAPI dependency signatures
from __future__ import annotations

import os
from datetime import datetime
from inspect import isawaitable
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import get_db

from .swes_r48_cc_event_validation import CCEventRejected, validate_cc_event
from .swes_r48_cc_https_attestor import attest_cc_signed_sender
from .swes_r48_ia0_ingest_auth import authorize_cc_ingest
from .swes_r48_ia0_writer import VerifiedCCEvent, persist_verified_event
from .swes_track_a_registered_order_scope import _RENDER, LOCATION, MERCHANT, TENANT

TRACK_A_FLAG = "XAFPAY_SWES_TRACK_A_IA0_ENABLED"
TRACK_A_PREFIX = "/internal/swes/track-a-sandbox"
router = APIRouter(prefix=TRACK_A_PREFIX, tags=["SWES R48 TRACK A TEST"])

_BINDING = text("""
SELECT b.public_id
FROM public.ia0_interaction_context_bindings b
JOIN public.ia0_interaction_sessions s
  ON s.tenant_id=b.tenant_id AND s.id=b.interaction_session_id
WHERE b.tenant_id=:tenant AND b.source_authority=:source
  AND b.source_reference=:event_id AND b.correlation_id=:correlation
  AND b.purpose_code='restaurant.customer_channel.checkout'
  AND b.provenance_authority='xafpay.cc.hosted_pg17_signed_twilio_receipt'
  AND b.source_hash=:fingerprint AND b.expires_at>now()
  AND s.verification_state='channel_verified'
""")

def _private_admission(env) -> bool:
    # Source only. The actual bilateral bearer, DB scope and HTTPS receipt
    # must ALSO pass; a feature flag never grants authorization by itself.
    return (
        env.get(TRACK_A_FLAG) == "1"
        and all(env.get(k) == v for k, v in _RENDER.items())
        and isinstance(env.get("RENDER_GIT_COMMIT"), str)
        and len(env["RENDER_GIT_COMMIT"]) == 40
        and all(c in "0123456789abcdef" for c in env["RENDER_GIT_COMMIT"])
    )

def _proof(event: dict, headers: dict) -> VerifiedCCEvent:
    event_id, correlation = validate_cc_event(event, headers)
    if (event.get("tenant_id") != TENANT
        or event.get("merchant_public_id") != str(MERCHANT)
        or event.get("location_id") not in (None, LOCATION)):
        raise CCEventRejected("TRACK_A_SCOPE_INVALID")
    receipt, sender = event["receipt"], event["sender_reference"]
    return VerifiedCCEvent(
        tenant_id=TENANT, location_id=LOCATION,
        event_id=event_id, fingerprint=receipt["payload_sha256"],
        sender_hmac=sender["value"], receipt_reference=receipt["reference"],
        correlation_ref=UUID(correlation),
        received_at=datetime.fromisoformat(
            event["server_received_at_utc"].replace("Z", "+00:00")
        ),
        expires_at=datetime.fromisoformat(
            event["delivered_before_utc"].replace("Z", "+00:00")
        ),
    )


@router.post("/first-ia0")
async def accept_track_a_first_ia0(request: Request, payload: dict = Body(...),
                                  db=Depends(get_db)):
    try:
        if not _private_admission(os.environ):
            raise CCEventRejected("TRACK_A_INACTIVE")
        if set(payload) - {
            "schema", "tenant_id", "merchant_public_id", "location_id",
            "audience", "context_purpose", "channel", "event_id",
            "correlation_ref", "provider_message_id", "sender_reference",
            "provider_endpoint_ref", "provider_account_ref",
            "server_received_at_utc", "delivered_before_utc",
            "receipt", "verification",
        }:
            raise CCEventRejected("UNRECOGNIZED_FIELDS")
        event = _proof(payload, {
            "X-CC-Event-Id": request.headers.get("X-CC-Event-Id"),
            "X-Idempotency-Key": request.headers.get("X-Idempotency-Key"),
            "X-Correlation-Ref": request.headers.get("X-Correlation-Ref"),
            "X-CC-Event-Schema": request.headers.get("X-CC-Event-Schema"),
        })
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.count(" ") != 1:
            raise CCEventRejected("SERVICE_BEARER_REQUIRED")
        bearer = auth[7:]
        if authorize_cc_ingest(db, bearer=bearer) is not True:
            raise CCEventRejected("SERVICE_NOT_AUTHORIZED")

        # This exact source's attestor makes the real WND→CC HTTPS call
        # (second distinct bilateral bearer), validates genuine processed
        # receipt provenance and signed sender binding. No JSON claim suffices.
        attested = attest_cc_signed_sender(event, payload)
        if isawaitable(attested):
            attested = await attested
        if attested is not True:
            raise CCEventRejected("RECEIPT_NOT_ATTESTED")

        def service_verifier(candidate):
            return candidate == event and authorize_cc_ingest(
                db, bearer=bearer
            ) is True

        def provenance_verifier(candidate):
            return candidate == event and attested is True

        session = persist_verified_event(
            db, event,
            authorize_service=service_verifier,
            verify_cc_receipt=provenance_verifier,
        )
        db.flush()
        binding_rows = db.execute(_BINDING, {
            "tenant": TENANT,
            "source": "xafpay.customer_channel.signed_twilio",
            "event_id": event.event_id,
            "correlation": str(event.correlation_ref),
            "fingerprint": event.fingerprint,
        }).scalars().all()
        if len(binding_rows) != 1:
            raise CCEventRejected("CANONICAL_CONTEXT_BINDING_MISSING_OR_AMBIGUOUS")
        context = UUID(str(binding_rows[0]))
        db.commit()
        return JSONResponse(status_code=202, content={
            "schema": "xafpay.wnd.swes.track_a.ia0_ack.v1",
            "event_id": event.event_id,
            "correlation_ref": str(event.correlation_ref),
            "ia0_session_ref": str(session.public_id),
            "context_binding_ref": str(context),
            "verification_state": "channel_verified",
            "order_state": "NOT_CREATED",
        })
    except (CCEventRejected, ValueError, KeyError, TypeError):
        db.rollback()
        return JSONResponse(status_code=403, content={
            "detail": "SWES_TRACK_A_IA0_NOT_AUTHORIZED"
        })
    except Exception:  # noqa: BLE001 - fail closed and suppress DB internals
        db.rollback()
        return JSONResponse(status_code=503, content={
            "detail": "SWES_TRACK_A_IA0_UNAVAILABLE"
        })


def install_track_a_first_ia0(app, *, environ=None) -> bool:
    env = environ if environ is not None else os.environ
    if not _private_admission(env):
        return False
    if getattr(app.state, "swes_track_a_first_ia0_installed", False):
        raise RuntimeError("TRACK_A_RECEIVER_ALREADY_INSTALLED")
    app.include_router(router)
    app.state.swes_track_a_first_ia0_installed = True
    return True
