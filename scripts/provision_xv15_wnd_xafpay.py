"""Provision the isolated WND tenant's neutral XafPay clearing account."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from database import SessionLocal
from core.domain.finance.operational_balance_contract import CreateOperationalAccountCommand
from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine

ACCOUNT_ID = uuid5(NAMESPACE_URL, "xbos:xv15:wnd:xafpay-v2:operational-account")
CORRELATION = uuid5(NAMESPACE_URL, "xbos:xv15:wnd:xafpay-v2:provision")


def main() -> None:
    database_name = os.environ.get("XV15_DATABASE_NAME", "")
    if database_name != "xbos_xafpay_xv15_r1":
        raise RuntimeError("XV15_DATABASE_NOT_AUTHORIZED")
    output = Path(os.environ["XV15_XBOS_RUNTIME_FILE"])
    with SessionLocal() as session:
        with session.begin():
            authority = session.execute(text("""
                SELECT t.id tenant_id,ou.id organization_unit_id
                  FROM tenants t JOIN organization_units ou ON ou.tenant_id=t.id
                 WHERE t.code='CM001' AND t.name='Wine & Dine'
                 ORDER BY ou.id LIMIT 1
            """)).mappings().one()
            tenant_id = int(authority["tenant_id"])
            organization_unit_id = int(authority["organization_unit_id"])
            existing = session.execute(text("""
                SELECT opened_at FROM operational_financial_accounts
                 WHERE tenant_id=:tenant AND public_id=:public_id
            """), {"tenant": tenant_id, "public_id": str(ACCOUNT_ID)}).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            session.execute(text("""
                INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata)
                VALUES('XAF','fiat','Central African CFA franc',0,8,true,CAST(:metadata AS jsonb))
                ON CONFLICT(code) DO UPDATE SET active=true
            """), {"metadata": json.dumps({"xv15_rehearsal": True})})
            session.execute(text("""
                INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
                VALUES(:tenant,'XAF','half_even',0,true,:now,1)
                ON CONFLICT(tenant_id,currency_code,policy_version) DO UPDATE SET active=true
            """), {"tenant": tenant_id, "now": now})
            account = TransactionalOperationalBalanceEngine.create_account(
                session,
                CreateOperationalAccountCommand(
                    public_id=ACCOUNT_ID,
                    tenant_id=tenant_id,
                    organization_unit_id=organization_unit_id,
                    account_class="commercial_settlement",
                    account_type="gateway",
                    code="xafpay_v2_clearing",
                    display_name="XafPay V2 clearing",
                    currency_code="XAF",
                    aggregation_role="leaf",
                    opened_at=existing or now,
                    correlation_id=CORRELATION,
                    actor_service="xbos.xafpay_v2",
                    source_component="xbos.xafpay_v2.provision",
                    source_record_id="xv15-wnd-xafpay-v2-clearing",
                    idempotency_scope="xafpay_v2.provision.account",
                    idempotency_key="xv15-wnd-xafpay-v2-clearing",
                    channel_code="xafpay",
                    reconciliation_enabled=True,
                    metadata={"purpose": "XV15 isolated WND rehearsal"},
                ),
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "tenant_id": tenant_id,
        "organization_unit_id": organization_unit_id,
        "operational_account_public_id": str(account.public_id),
    }, indent=2, sort_keys=True), encoding="utf-8")
    print("XV15_R1_WND_OPERATIONAL_ACCOUNT=PASS")


if __name__ == "__main__":
    main()
