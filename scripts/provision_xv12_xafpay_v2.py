"""Provision one XBOS-owned clearing account for the isolated XV12 tenant."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import text

from database import SessionLocal
from core.domain.finance.operational_balance_contract import CreateOperationalAccountCommand
from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine

TENANT_CODE = "XAFPAYXV12"
ACCOUNT_ID = uuid5(NAMESPACE_URL, "xbos:xv12:xafpay-v2:operational-account")
CORRELATION = uuid5(NAMESPACE_URL, "xbos:xv12:xafpay-v2:provision")


def main() -> None:
    output = Path(os.environ.get("XV12_XBOS_RUNTIME_FILE", str(Path.home() / "xv12-xbos-runtime.json")))
    with SessionLocal() as session:
        with session.begin():
            authority = session.execute(text("""
                SELECT t.id AS tenant_id,ou.id AS organization_unit_id
                  FROM public.tenants t
                  JOIN public.organization_units ou ON ou.tenant_id=t.id
                 WHERE t.code=:code
                 ORDER BY ou.id LIMIT 1
            """), {"code": TENANT_CODE}).mappings().one()
            tenant_id = int(authority["tenant_id"]); org_id = int(authority["organization_unit_id"])
            # Account creation is content-addressed by the full immutable command,
            # including opened_at. R1 may be rerun after a prior revision already
            # created the deterministic clearing account, so reuse its persisted
            # opening timestamp on replay instead of generating a new fingerprint.
            existing_opened_at = session.execute(text("""
                SELECT opened_at
                  FROM public.operational_financial_accounts
                 WHERE tenant_id=:tenant_id AND public_id=:public_id
            """), {"tenant_id": tenant_id, "public_id": str(ACCOUNT_ID)}).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            account_opened_at = existing_opened_at or now
            # A freshly migrated neutral XBOS database has schema authority but no
            # finance reference rows. Seed only the canonical XAF reference data
            # required by this isolated tenant, using the same idempotent pattern
            # as the approved M4/M6 finance verifiers.
            session.execute(text("""
                INSERT INTO public.currency_assets(
                    code, asset_kind, display_name, minor_unit_scale,
                    maximum_storage_scale, active, metadata
                ) VALUES (
                    'XAF', 'fiat', 'Central African CFA franc', 0, 8, true,
                    '{"xv12_reference_data": true}'::jsonb
                )
                ON CONFLICT(code) DO UPDATE SET active=true
            """))
            session.execute(text("""
                INSERT INTO public.tenant_currency_policies(
                    tenant_id, currency_code, rounding_mode, cash_rounding_increment,
                    active, effective_from, policy_version
                ) VALUES (
                    :tenant_id, 'XAF', 'half_even', 0, true, :effective_from, 1
                )
                ON CONFLICT(tenant_id, currency_code, policy_version)
                DO UPDATE SET active=true
            """), {"tenant_id": tenant_id, "effective_from": now})
            account = TransactionalOperationalBalanceEngine.create_account(session, CreateOperationalAccountCommand(
                public_id=ACCOUNT_ID, tenant_id=tenant_id, organization_unit_id=org_id,
                account_class="commercial_settlement", account_type="gateway", code="xafpay_v2_clearing",
                display_name="XafPay V2 clearing", currency_code="XAF", aggregation_role="leaf",
                opened_at=account_opened_at, correlation_id=CORRELATION,
                actor_service="xbos.xafpay_v2", source_component="xbos.xafpay_v2.provision",
                source_record_id="xv12-xafpay-v2-clearing", idempotency_scope="xafpay_v2.provision.account",
                idempotency_key="xv12-xafpay-v2-clearing", channel_code="xafpay",
                reconciliation_enabled=True, metadata={"purpose":"XV12 isolated Gateway V2 proof"},
            ))
            wnd = session.execute(text("SELECT count(*) FROM public.tenants WHERE upper(code) LIKE '%WND%' OR upper(name) LIKE '%WINE%DINE%'" )).scalar_one()
            if int(wnd) != 0:
                raise RuntimeError("XV12_WND_TENANT_ISOLATION_FAILED")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "tenant_id": tenant_id,
        "organization_unit_id": org_id,
        "operational_account_public_id": str(account.public_id),
    }, indent=2, sort_keys=True), encoding="utf-8")
    print("XV12_R1_XAF_CURRENCY_REFERENCE=PASS")
    print(f"XV12_R1_CLEARING_ACCOUNT_PROVISION_REPLAY=PASS mode={'replay' if existing_opened_at is not None else 'create'}")
    print("XV12_XBOS_CLEARING_ACCOUNT=PASS")
    print("XV12_12_TENANT_LOCATION_ISOLATION_BASELINE=PASS")

if __name__ == "__main__": main()
