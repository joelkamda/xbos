"""Verify pending/no-value and success/exactly-once control totals in isolated XBOS."""
from __future__ import annotations
import json,os,sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from uuid import UUID
from database import SessionLocal
from core.integrations.xafpay_v2.repository import XafPayV2Repository

mode=sys.argv[1] if len(sys.argv)>1 else ""
state=json.loads(Path(os.environ["XV12_R1_STATE_FILE"]).read_text(encoding="utf-8"))
attempt=UUID(state["attempt_public_id"])
with SessionLocal() as session:
    snap=XafPayV2Repository.snapshot_for_attempt(session,attempt)
if snap["tenant_id"] != state["tenant_id"] or snap["organization_unit_id"] != state["organization_unit_id"]:
    raise SystemExit("XV12_SCOPE_CHANGED")
if snap["provider_account_id"] is not None or snap["underlying_provider_code"] is not None:
    raise SystemExit("XV12_PROVIDER_AUTHORITY_LEAK")
if mode=="pending":
    if int(snap["confirmed_settlements"]) != 0 or snap["attempt_state"] == "succeeded":
        raise SystemExit("XV12_PENDING_CREATED_SETTLED_VALUE")
    print("XV12_3_PENDING_NO_SETTLEMENT=PASS")
elif mode=="success":
    if snap["attempt_state"] != "succeeded" or int(snap["confirmed_settlements"]) != 1:
        raise SystemExit(f"XV12_SUCCESS_CONTROL_TOTAL_FAILED:{snap}")
    print("XV12_4_SUCCESS_EXACTLY_ONCE=PASS")
else:
    raise SystemExit("usage: verify_xv12_r1_state.py pending|success")
print("XV12_12_TENANT_LOCATION_ISOLATION=PASS")
