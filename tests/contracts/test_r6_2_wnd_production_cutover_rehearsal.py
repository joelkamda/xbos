from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from restaurant.r6.cutover_rehearsal import (
    CONTROL_NAMES,
    WithheldLedger,
    assert_complete_reconciliation,
    deterministic_public_id,
    semantic_hash,
    wnd_business_date,
    zero_controls,
)

ROOT = Path(__file__).resolve().parents[2]


def test_r6_2_contract_is_non_production_and_recovery_first():
    contract = json.loads(
        (ROOT / "contracts/restaurant/v1/r6_2_production_cutover_rehearsal_authority.json").read_text()
    )
    assert contract["source_checkpoint"] == "0f4c72ff297b580c9a2572fe6a0068d814b22267"
    assert contract["source_archive_sha256"] == "9c789845bf8f2a68ab0de9d87707eac492e109a8e646c4533e915e181e6a1c94"
    assert contract["production_database"] == "xbos"
    assert contract["production_write_authorized"] is False
    assert contract["writer_routing"] == "unchanged"
    assert set(contract["rehearsal_databases"]) == {"xbos_r6_2_source", "xbos_r6_2_candidate"}
    assert contract["r6_2_pass_meaning"].endswith("PASS does not authorize live cutover")


def test_r6_2_business_date_uses_wnd_0800_boundary():
    assert wnd_business_date(datetime(2026, 8, 21, 6, 59, tzinfo=timezone.utc)).isoformat() == "2026-08-20"
    assert wnd_business_date(datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)).isoformat() == "2026-08-21"


def test_r6_2_naive_legacy_ar_timestamp_is_treated_as_utc_wall_clock():
    # 06:59 naive is 07:59 Douala and therefore belongs to the preceding WND business date.
    assert wnd_business_date(datetime(2026, 8, 21, 6, 59)).isoformat() == "2026-08-20"


def test_r6_2_withheld_reconciliation_is_explicit_not_silent():
    source = zero_controls()
    source["commercial_revenue"] = Decimal("100")
    source["customer_allowances"] = Decimal("10")
    mapped = zero_controls()
    mapped["commercial_revenue"] = Decimal("80")
    withheld = WithheldLedger()
    withheld.add(
        source_identity="sale:1",
        reason="legacy_sale_allowance_equation_incompatible",
        controls={"commercial_revenue": Decimal("20"), "customer_allowances": Decimal("10")},
    )
    assert_complete_reconciliation(source, mapped, withheld.controls)
    assert withheld.counts == {"legacy_sale_allowance_equation_incompatible": 1}
    assert len(withheld.fingerprint) == 64


def test_r6_2_unreconciled_control_fails_closed():
    source = zero_controls()
    source["cash_collections"] = Decimal("10")
    with pytest.raises(ValueError, match="unreconciled control cash_collections"):
        assert_complete_reconciliation(source, zero_controls(), zero_controls())


def test_r6_2_deterministic_shadow_public_ids_are_stable_and_scoped():
    a = deterministic_public_id("operational-account", 2, 1, "cash")
    b = deterministic_public_id("operational-account", 2, 1, "cash")
    c = deterministic_public_id("operational-account", 2, 1, "mtn")
    assert a == b
    assert a != c


def test_r6_2_semantic_hash_is_order_insensitive_for_mapping_keys():
    assert semantic_hash({"b": 2, "a": 1}) == semantic_hash({"a": 1, "b": 2})


def test_r6_2_control_names_remain_exact_m73_controls():
    assert CONTROL_NAMES == (
        "commercial_revenue",
        "customer_allowances",
        "cash_collections",
        "receivables_opened",
        "receivables_satisfied",
        "refunds",
        "fulfillment_cost",
        "financial_documents",
    )


def test_r6_2_acceptance_script_preserves_authority_boundaries():
    source = (ROOT / "scripts/verify_r6_2_wnd_production_cutover_rehearsal.py").read_text()
    required = (
        'SOURCE_DATABASE = "xbos_r6_2_source"',
        'CANDIDATE_DATABASE = "xbos_r6_2_candidate"',
        '"production_writes": "NONE"',
        '"writer_routing": "UNCHANGED"',
        '"live_cutover_authorized": False',
        "R6_2_POSTGRES_CUTOVER_REHEARSAL=PASS",
        "legacy_sale_allowance_equation_incompatible",
        "noncash_external_settlement_identity_missing",
        "historical_receivable_satisfaction_without_explicit_repayment",
        "historical_document_content_hash_unavailable",
        "WITHHELD_NOT_ZERO_ECONOMIC_COST",
        "R6_2_UNCLASSIFIED_CONTROL_AMOUNT",
    )
    for marker in required:
        assert marker in source


def test_r6_2_acceptance_reuses_frozen_r61_restore_adoption_harness_only_for_disposable_names():
    source = (ROOT / "scripts/verify_r6_2_wnd_production_cutover_rehearsal.py").read_text()
    assert "import scripts.verify_r6_1_wnd_rehearsal_adoption as r61" in source
    assert "r61.SOURCE_DATABASE = SOURCE_DATABASE" in source
    assert "r61.CANDIDATE_DATABASE = CANDIDATE_DATABASE" in source
    assert "r61.DISPOSABLE_DATABASES = DISPOSABLE_DATABASES" in source
    assert "r61._adopt_candidate()" in source
    assert "r61._register_and_compose_candidate()" in source


def test_r6_2_no_schema_migration_artifacts():
    assert not list((ROOT / "alembic_neutral/versions").glob("r6_2*"))
    assert not list((ROOT / "alembic_neutral/sql").glob("r6_2*"))


def test_r6_2_control_scope_freezes_no_invented_cogs_rule():
    contract = json.loads(
        (ROOT / "contracts/restaurant/v1/r6_2_financial_control_scope.json").read_text()
    )
    assert contract["frozen_observed_controls"]["historical_inventory_mismatch_count"] == 156
    assert contract["frozen_observed_controls"]["historical_inventory_delta"] == "1995833"
    assert "never be interpreted as zero economic COGS" in contract["fulfillment_cost_note"]

def test_r6_2_does_not_use_generic_residual_withholding():
    source = (ROOT / "scripts/verify_r6_2_wnd_production_cutover_rehearsal.py").read_text()
    assert 'reason=f"explicit_residual_' not in source
    assert "R6_2_UNCLASSIFIED_CONTROL_AMOUNT" in source
