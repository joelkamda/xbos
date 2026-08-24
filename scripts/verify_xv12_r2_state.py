"""Verify XV12 R2 hostile-event, replay, conflict, and ordering control totals."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from database import SessionLocal
from core.integrations.xafpay_v2.repository import XafPayV2Repository


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"XV12_R2_CONFIG:{name}")
    return value


mode = sys.argv[1] if len(sys.argv) > 1 else ""
state = json.loads(Path(required("XV12_R2_STATE_FILE")).read_text(encoding="utf-8"))
attempt = UUID(state["attempt_public_id"])

with SessionLocal() as session:
    snap = XafPayV2Repository.snapshot_for_attempt(session, attempt)
    if snap["tenant_id"] != state["tenant_id"] or snap["organization_unit_id"] != state["organization_unit_id"]:
        raise SystemExit("XV12_R2_SCOPE_CHANGED")
    if snap["provider_account_id"] is not None or snap["underlying_provider_code"] is not None:
        raise SystemExit("XV12_R2_PROVIDER_AUTHORITY_LEAK")

    if mode == "failed":
        if snap["attempt_state"] != "failed" or int(snap["confirmed_settlements"]) != 0:
            raise SystemExit(f"XV12_R2_FAILED_EFFECT_VIOLATION:{snap}")
        print("XV12_5_FAILED_NO_SUCCESS_EFFECT=PASS")
    elif mode == "canceled":
        if snap["attempt_state"] != "cancelled" or int(snap["confirmed_settlements"]) != 0:
            raise SystemExit(f"XV12_R2_CANCELED_EFFECT_VIOLATION:{snap}")
        print("XV12_5_CANCELED_NO_SUCCESS_EFFECT=PASS")
    elif mode == "expired":
        if snap["attempt_state"] == "succeeded" or int(snap["confirmed_settlements"]) != 0:
            raise SystemExit(f"XV12_R2_EXPIRED_EFFECT_VIOLATION:{snap}")
        print("XV12_5_EXPIRED_NO_SUCCESS_EFFECT=PASS")
    elif mode in {"duplicate", "conflict"}:
        event_id = str(state.get("r2_success_event_id", "")).strip()
        fingerprint = str(state.get("r2_success_event_fingerprint", "")).strip()
        if not event_id or not fingerprint:
            raise SystemExit("XV12_R2_SUCCESS_EVENT_EVIDENCE_MISSING")
        row = session.execute(
            text(
                """
                SELECT request_fingerprint,processing_state,response_snapshot
                  FROM public.idempotency_records
                 WHERE tenant_id=:tenant_id AND scope='xafpay_v2.event' AND idempotency_key=:event_id
                """
            ),
            {"tenant_id": int(state["tenant_id"]), "event_id": event_id},
        ).mappings().one()
        if str(row["request_fingerprint"]) != fingerprint or str(row["processing_state"]) != "completed":
            raise SystemExit(f"XV12_R2_EVENT_EVIDENCE_CHANGED:{dict(row)}")
        response = row["response_snapshot"] or {}
        if response.get("event_type") != "payment.succeeded" or response.get("replayed") is not False:
            raise SystemExit(f"XV12_R2_EVENT_EVIDENCE_SNAPSHOT_CHANGED:{response}")
        if snap["attempt_state"] != "succeeded" or int(snap["confirmed_settlements"]) != 1:
            raise SystemExit(f"XV12_R2_SUCCESS_CARDINALITY_CHANGED:{snap}")
        if mode == "duplicate":
            print("XV12_6_DUPLICATE_EVENT_EXACTLY_ONE_EFFECT=PASS")
        else:
            print("XV12_7_CONFLICT_EVIDENCE_PRESERVED=PASS")
    elif mode in {"late_pending", "late_failed"}:
        if snap["attempt_state"] != "succeeded" or int(snap["confirmed_settlements"]) != 1:
            raise SystemExit(f"XV12_R2_BACKWARD_MUTATION:{mode}:{snap}")
        if mode == "late_pending":
            print("XV12_8_LATE_PENDING_NO_BACKWARD_MUTATION=PASS")
        else:
            print("XV12_8_LATE_FAILED_NO_BACKWARD_MUTATION=PASS")
    else:
        raise SystemExit("usage: verify_xv12_r2_state.py failed|canceled|expired|duplicate|conflict|late_pending|late_failed")

print("XV12_12_TENANT_LOCATION_ISOLATION=PASS")
