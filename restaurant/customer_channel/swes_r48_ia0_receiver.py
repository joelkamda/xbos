"""R48 TEST-only WND CC ingress; disabled unless trusted attestor is installed."""
# ruff: noqa: B008, BLE001
from datetime import datetime
from inspect import isawaitable
from uuid import UUID

from database import get_db
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from .swes_r48_cc_event_validation import CCEventRejected, validate_cc_event
from .swes_r48_ia0_ingest_auth import authorize_cc_ingest
from .swes_r48_ia0_writer import VerifiedCCEvent, persist_verified_event

router = APIRouter(prefix="/internal/swes/track-a/test-only", tags=["SWES R48 TEST"])

@router.post("/ia0-events")
async def accept_cc_event(request: Request, payload: dict = Body(...), db=Depends(get_db)):
    """The attest function MUST independently check processed CC receipt evidence.

    No trust callback installed -> HTTP 403. Claims in payload cannot admit it.
    """
    try:
        attest = getattr(request.app.state, "swes_r48_cc_receipt_attestor", None)
        if not callable(attest):
            raise CCEventRejected("INDEPENDENT_CC_ATTESTOR_REQUIRED")
        event_id, correlation = validate_cc_event(payload, {
            "X-CC-Event-Id": request.headers.get("X-CC-Event-Id"),
            "X-Idempotency-Key": request.headers.get("X-Idempotency-Key"),
            "X-Correlation-Ref": request.headers.get("X-Correlation-Ref"),
            "X-CC-Event-Schema": request.headers.get("X-CC-Event-Schema"),
        })
        raw_auth = request.headers.get("Authorization", "")
        if not raw_auth.startswith("Bearer ") or raw_auth.count(" ") != 1:
            raise CCEventRejected("INGEST_AUTH_FORBIDDEN")
        bearer = raw_auth[7:]
        if authorize_cc_ingest(db, bearer=bearer) is not True:
            raise CCEventRejected("INGEST_AUTH_FORBIDDEN")
        receipt = payload["receipt"]
        sender = payload["sender_reference"]
        proof = VerifiedCCEvent(
            tenant_id=payload["tenant_id"], location_id=5,
            event_id=event_id, fingerprint=receipt["payload_sha256"],
            sender_hmac=sender["value"], receipt_reference=receipt["reference"],
            correlation_ref=UUID(correlation),
            received_at=datetime.fromisoformat(payload["server_received_at_utc"].replace("Z","+00:00")),
            expires_at=datetime.fromisoformat(payload["delivered_before_utc"].replace("Z","+00:00")),
        )
        # attest must use trusted, independently verified CC receipt data,
        # not simply return the payload's provider_signature_verified claim.
        attestation = attest(proof, payload)
        if isawaitable(attestation):
            attestation = await attestation
        if attestation is not True:
            raise CCEventRejected("CC_PROVENANCE_NOT_ATTESTED")
        result = persist_verified_event(
            db, proof,
            authorize_service=lambda _: True,  # already checked WND bearer + role above
            verify_cc_receipt=lambda _: True,  # already independently attested above
        )
        db.commit()
        return JSONResponse(status_code=202, content={
            "event_id": event_id, "correlation_ref": correlation,
            "ia0_session_public_id": str(result.public_id),
            "ia0_conversation_public_id": str(result.conversation_public_id),
            "ia0_participant_public_id": str(result.participant_public_id),
            "verification_state": "channel_verified",
        })
    except (CCEventRejected, ValueError, KeyError, TypeError):
        db.rollback()
        return JSONResponse(status_code=403, content={"detail":"R48_EVENT_NOT_AUTHORIZED"})
    except Exception:
        db.rollback()
        return JSONResponse(status_code=503, content={"detail":"R48_RECEIVER_UNAVAILABLE"})

def install_cc_receiver(app, *, independently_verified_attestor=None):
    """Never publish a partially configured receiver."""
    if not callable(independently_verified_attestor):
        return False
    if getattr(app.state, "swes_r48_cc_receipt_attestor", None) is not None:
        raise RuntimeError("CC_RECEIVER_ALREADY_INSTALLED")
    app.state.swes_r48_cc_receipt_attestor=independently_verified_attestor
    app.include_router(router)
    return True
