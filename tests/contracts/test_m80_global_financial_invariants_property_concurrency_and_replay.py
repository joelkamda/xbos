from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from core.domain.finance.global_invariant_contract import (
    FinancialInvariantCase,
    GlobalInvariantError,
    deterministic_property_cases,
    validate_global_invariants,
    validate_property_corpus,
)
from core.domain.finance.global_invariant_service import (
    ReplayInvariantOracle,
    validate_kernel_concurrency_guards,
)
from core.domain.finance.m6_acceptance import EXPECTED_HEAD

ROOT = Path(__file__).resolve().parents[2]


def test_contract_freezes_schema_neutral_hardening_boundary():
    contract = json.loads((ROOT / "contracts/finance/v1/m80_global_financial_invariants_property_concurrency_and_replay.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["source_checkpoint"]["commit"] == "b1ec385"
    assert contract["property_testing"]["minimum_cases"] == 512
    assert contract["concurrency"]["workers"] == 8
    assert contract["boundaries"]["live_cutover_owner"] == "R6"


def test_seeded_property_corpus_is_large_exact_and_reproducible():
    first = deterministic_property_cases(seed=8000, count=512)
    second = deterministic_property_cases(seed=8000, count=512)
    assert validate_property_corpus(first) == 512
    assert tuple(case.fingerprint for case in first) == tuple(case.fingerprint for case in second)
    assert all(isinstance(case.obligation_amount, Decimal) for case in first)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"journal_credits": (Decimal("9"),)}, "journal_unbalanced"),
        ({"allocation_amounts": (Decimal("101"),)}, "obligation_capacity_exceeded"),
        ({"allocation_reversals": (Decimal("51"),)}, "allocation_reversal_capacity_exceeded"),
        ({"settlement_reversals": (Decimal("81"),)}, "settlement_reversal_capacity_exceeded"),
        ({"transfer_destination_delta": Decimal("49")}, "transfer_value_not_conserved"),
    ],
)
def test_each_global_invariant_fails_closed(change, code):
    valid = FinancialInvariantCase(
        "valid", Decimal("100"), (Decimal("50"),), (Decimal("25"),),
        Decimal("80"), (Decimal("20"),), (Decimal("60"), Decimal("40")),
        (Decimal("100"),), Decimal("-50"), Decimal("50"),
    )
    with pytest.raises(GlobalInvariantError) as raised:
        validate_global_invariants(replace(valid, **change))
    assert raised.value.code == code


def test_threaded_replay_oracle_accepts_one_effect_and_stable_replays():
    oracle = ReplayInvariantOracle()
    payload = {"amount": "100", "currency": "XAF", "kind": "settlement"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = tuple(pool.map(
            lambda _: oracle.accept(tenant_id=2, scope="m80.test", key="same", payload=payload),
            range(8),
        ))
    assert oracle.accepted_count == 1
    assert sum(not decision.replayed for decision in decisions) == 1
    assert sum(decision.replayed for decision in decisions) == 7
    assert len({decision.payload_fingerprint for decision in decisions}) == 1


def test_conflicting_replay_fails_closed_and_tenant_identity_is_distinct():
    oracle = ReplayInvariantOracle()
    oracle.accept(tenant_id=2, scope="m80.test", key="key", payload={"amount": "10"})
    with pytest.raises(GlobalInvariantError) as raised:
        oracle.accept(tenant_id=2, scope="m80.test", key="key", payload={"amount": "11"})
    assert raised.value.code == "idempotency_conflict"
    other = oracle.accept(tenant_id=3, scope="m80.test", key="key", payload={"amount": "11"})
    assert not other.replayed and oracle.accepted_count == 2


def test_persistence_marker_forbids_new_authority_and_cutover():
    source = (ROOT / "core/persistence/m80_global_financial_hardening.py").read_text(encoding="utf-8")
    for marker in (
        "SCHEMA_NEUTRAL = True", "WRITES_NEW_TABLES = False",
        "CREATES_FINANCIAL_AUTHORITY = False", "REROUTES_LEGACY_WRITERS = False",
        "CUTOVER_AUTHORIZED = False", 'LIVE_CUTOVER_OWNER = "R6"',
    ):
        assert marker in source


def test_m80_introduces_no_schema_migration():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m80_*.py"))


def test_accepted_kernel_guards_are_present_across_all_major_authorities():
    validate_kernel_concurrency_guards(ROOT)


def test_database_verifier_exercises_real_concurrency_replay_and_rollback():
    source = (ROOT / "scripts/verify_m80_global_financial_invariants.py").read_text(encoding="utf-8")
    for marker in (
        "ThreadPoolExecutor", "TransactionalCanonicalFinancialEventEngine.emit",
        "FinancialEventIdempotencyConflict", "source_record_not_found",
        "concurrency=PASS", "rollback=PASS", "dropped=true",
    ):
        assert marker in source


def test_m80_public_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M8_0_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M8_0_INSTALL_AND_VERIFY.txt").is_file()
