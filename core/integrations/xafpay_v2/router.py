"""Signed internal-consumer endpoint for XafPay Gateway V2 events."""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import SessionLocal

from .contract import XafPayV2IntegrationError
from .service import XafPayV2Service

router = APIRouter()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise RuntimeError(f"XV12_XAFPAY_V2_CONFIG:{name}")
    return value


@router.post("/events")
async def receive_gateway_event(request: Request):
    raw_body = await request.body()
    headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
    try:
        signing_secret = _required("XAFPAY_XBOS_EVENT_SIGNING_SECRET")
        merchant_id = _required("XAFPAY_V2_GATEWAY_MERCHANT_ID")
        account_id = UUID(_required("XAFPAY_V2_OPERATIONAL_ACCOUNT_PUBLIC_ID"))
        replay_window = int(os.getenv("XAFPAY_V2_REPLAY_WINDOW_SECONDS", "300"))
        with SessionLocal() as session:
            with session.begin():
                result = XafPayV2Service.consume_event(
                    session,
                    raw_body=raw_body,
                    headers=headers,
                    signing_secret=signing_secret,
                    expected_gateway_merchant_id=merchant_id,
                    operational_account_public_id=account_id,
                    replay_window_seconds=replay_window,
                )
        return JSONResponse(status_code=200, content=dict(result))
    except XafPayV2IntegrationError as exc:
        if exc.code in {"signature_invalid", "signature_timestamp_invalid", "signature_replay_window"}:
            status = 401
        elif exc.code in {"event_identity_conflict", "terminal_success_conflict", "settlement_cardinality_conflict"}:
            status = 409
        else:
            status = 400
        return JSONResponse(status_code=status, content={"detail": exc.code})
