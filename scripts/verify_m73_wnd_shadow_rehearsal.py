"""Read-only M7.3 acceptance verifier."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_inventory import EXPECTED_HEAD, verify_no_writer_rerouting
from core.domain.finance.m6_acceptance import validate_release_manifest as validate_m6_manifest
from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService
from core.domain.finance.wnd_shadow_rehearsal_contract import FinancialControlTotals, assert_rehearsal_replay
from core.domain.finance.wnd_shadow_rehearsal_service import WndShadowRehearsalService
from database import engine


def main() -> int:
    if validate_m6_manifest(ROOT).canonical_head != EXPECTED_HEAD:
        raise RuntimeError("M6 freeze changed")
    verify_no_writer_rerouting(ROOT)
    envelope = LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=LegacySourceFamily.COMMERCIAL,
        source_record_type="commercial_sale", source_record_id="production-shape-1",
        source_updated_at=datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc),
        business_date=date(2026, 8, 11), correlation_id=UUID("73000000-0000-0000-0000-000000000001"),
        payload={"kind": "commercial_sale", "gross_amount": "100", "discount_amount": "10",
                 "complimentary_amount": "5", "collected_amount": "60", "unpaid_amount": "25",
                 "currency_code": "XAF", "revenue_nature": "food", "discount_reason": "promotion",
                 "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery"},
    )
    mapping = WndFinancialMappingService.map(envelope)
    case = WndShadowRehearsalService.financial_case(1, mapping)
    rehearsal = WndShadowRehearsalService.assemble("m73-production-shaped", "a" * 64, (case,))
    replay = WndShadowRehearsalService.assemble("m73-production-shaped", "a" * 64, (case,))
    assert assert_rehearsal_replay(rehearsal, replay) is rehearsal
    matched = WndShadowRehearsalService.compare(case, case.expected)
    variance = WndShadowRehearsalService.compare(case, FinancialControlTotals("XAF", {
        "commercial_revenue": Decimal("99"), "customer_allowances": 15, "receivables_opened": 25,
    }))
    assert matched.status == "matched" and variance.status == "variance"
    assert rehearsal.writer_routing == "unchanged" and rehearsal.live_cutover_owner == "R6"
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev" or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
    print(f"database={database}")
    print(f"revision={revision}")
    print("m73_wnd_shadow_rehearsal=PASS shadow=PASS production_shape=PASS control_totals=PASS "
          "variance=PASS replay=PASS writer_routing=UNCHANGED migration=NONE cutover_owner=R6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
