"""Read-only M7.4 dual-read, readiness, and retirement-support verifier."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_contract import AuthorityMode
from core.domain.finance.legacy_authority_inventory import (
    EXPECTED_HEAD, load_inventory, verify_no_writer_rerouting,
)
from core.domain.finance.m6_acceptance import validate_release_manifest as validate_m6_manifest
from core.domain.finance.wnd_cutover_support_contract import (
    REQUIRED_READINESS_EVIDENCE, DualReadProjection, ReadinessEvidence,
)
from core.domain.finance.wnd_cutover_support_service import WndCutoverSupportService
from core.domain.finance.wnd_shadow_rehearsal_contract import FinancialControlTotals
from database import engine


def main() -> int:
    if validate_m6_manifest(ROOT).canonical_head != EXPECTED_HEAD:
        raise RuntimeError("M6 freeze changed")
    verify_no_writer_rerouting(ROOT)
    inventory = load_inventory(ROOT)
    as_of = datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc)
    totals = FinancialControlTotals("XAF", {
        "commercial_revenue": "100", "customer_allowances": "15",
        "receivables_opened": "25", "cash_collections": "60",
    })
    legacy = DualReadProjection("legacy", 2, 1, "commercial", "sale:7401", as_of, totals, "a" * 64)
    canonical = DualReadProjection("canonical", 2, 1, "commercial", "sale:7401", as_of, totals, "b" * 64)
    comparison = WndCutoverSupportService.compare(legacy, canonical)
    hash_chars = "abcdef012"
    evidence = tuple(ReadinessEvidence(
        code=code, passed=True, evidence_hash=hash_chars[index] * 64,
        observed_at=as_of, detail=f"verified {code}",
    ) for index, code in enumerate(REQUIRED_READINESS_EVIDENCE))
    assessment = WndCutoverSupportService.assess("m74-readiness", "f" * 64, evidence)
    writer_surfaces = tuple(surface for surface in inventory.surfaces
                            if surface.authority_mode in {AuthorityMode.WRITER, AuthorityMode.READER_WRITER})
    rollbacks = {surface.code: f"runbook://rollback/{surface.code}" for surface in writer_surfaces}
    retirement = WndCutoverSupportService.retirement_plan(
        "m74-writer-retirement", assessment, inventory, rollbacks
    )
    if comparison.status != "matched" or assessment.status != "ready_for_r6_review":
        raise RuntimeError("compatibility or readiness failed")
    if assessment.cutover_authorized or retirement.execution_allowed:
        raise RuntimeError("M7.4 acquired cutover authority")
    if any(item.retirement_executed for item in retirement.candidates):
        raise RuntimeError("legacy writer was retired")
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev" or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
    print(f"database={database}")
    print(f"revision={revision}")
    print(f"m74_wnd_cutover_support=PASS dual_read=PASS readiness=PASS retirement_candidates={len(retirement.candidates)}")
    print("m74_authority_boundary=PASS read_mode=LEGACY_PRIMARY_CANONICAL_SHADOW writer_routing=UNCHANGED cutover=NOT_AUTHORIZED retirement=NOT_EXECUTED cutover_owner=R6 migration=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
