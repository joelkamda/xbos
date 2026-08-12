from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.domain.finance.adversarial_ordering_contract import (
    AdversarialControlError, AuthorityProbe, DelayedFinancialFact, fact_digest,
)
from core.domain.finance.adversarial_ordering_service import (
    authorize, order_offline_facts, validate_authority_sources,
)
from core.domain.finance.m6_acceptance import EXPECTED_HEAD

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
BASE = datetime(2026, 8, 11, 8, tzinfo=UTC)


def fact(number: int, *, occurred_hours: int, received_hours: int, tenant: int = 2, org: int = 1):
    return DelayedFinancialFact(
        tenant, org, "wnd.offline", f"sale-{number}", number,
        BASE + timedelta(hours=occurred_hours), BASE + timedelta(hours=received_hours),
        date(2026, 8, 11), "commercial_fact", fact_digest({"number": number}),
    )


def raises(code, action):
    with pytest.raises(AdversarialControlError) as raised:
        action()
    assert raised.value.code == code


def test_contract_freezes_schema_neutral_boundary():
    contract = json.loads((ROOT / "contracts/finance/v1/m81_ordering_offline_isolation_and_authorization.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["source_checkpoint"]["commit"] == "e0feabe"
    assert contract["migration"] is False
    assert contract["ordering"]["arrival_order_is_authority"] is False
    assert contract["boundaries"]["live_cutover_owner"] == "R6"


def test_arrival_order_never_replaces_economic_order():
    late_arrival = fact(1, occurred_hours=1, received_hours=8)
    early_arrival = fact(2, occurred_hours=5, received_hours=6)
    projection = order_offline_facts((early_arrival, late_arrival))
    assert tuple(value.source_record_id for value in projection.facts) == ("sale-1", "sale-2")
    assert projection.facts[0].received_at > projection.facts[1].received_at


def test_offline_identical_replay_is_one_effect_and_conflict_fails_closed():
    original = fact(1, occurred_hours=1, received_hours=8)
    projection = order_offline_facts((original, original))
    assert len(projection.facts) == 1 and projection.replay_count == 1
    raises("idempotency_conflict", lambda: order_offline_facts((
        original, replace(original, payload_fingerprint=fact_digest({"changed": True})),
    )))


@pytest.mark.parametrize("changed", [{"tenant_id": 3}, {"organization_unit_id": 2}])
def test_cross_scope_projection_fails_closed(changed):
    raises("scope_mismatch", lambda: order_offline_facts((fact(1, occurred_hours=1, received_hours=2), replace(fact(2, occurred_hours=2, received_hours=3), **changed))))


def test_permissions_and_governed_reopen_separation():
    authorize(AuthorityProbe(2, 1, "reconcile", 7, frozenset({"accounting.reconcile"})))
    raises("permission_denied", lambda: authorize(AuthorityProbe(2, 1, "close_period", 7, frozenset({"accounting.reconcile"}))))
    base = AuthorityProbe(2, 1, "reopen_period", 7, frozenset({"accounting.close_period"}), 8, frozenset({"accounting.close_period"}), "abc")
    authorize(base)
    raises("approval_separation_required", lambda: authorize(replace(base, approved_by_user_id=7)))
    raises("approver_permission_denied", lambda: authorize(replace(base, approver_permissions=frozenset())))
    raises("approval_evidence_required", lambda: authorize(replace(base, evidence_fingerprint=None)))


def test_existing_kernel_remains_authority_for_permissions_and_close_history():
    validate_authority_sources(ROOT)


def test_m81_is_schema_neutral_and_does_not_reroute_writers():
    source = (ROOT / "core/persistence/m81_ordering_offline_security_hardening.py").read_text(encoding="utf-8")
    for marker in ("SCHEMA_NEUTRAL = True", "WRITES_NEW_TABLES = False", "CREATES_CHRONOLOGY_AUTHORITY = False", "CREATES_PERMISSION_AUTHORITY = False", "REROUTES_LEGACY_WRITERS = False", "CUTOVER_AUTHORIZED = False"):
        assert marker in source
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m81_*.py"))


def test_verifier_and_public_gate_exist():
    verifier = (ROOT / "scripts/verify_m81_ordering_offline_isolation_authorization.py").read_text(encoding="utf-8")
    for marker in ("occurred_at", "recorded_at", "organization_unit_not_active", "ordering=PASS", "offline=PASS", "permissions=PASS"):
        assert marker in verifier
    assert (ROOT / "XBOS_M8_1_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M8_1_INSTALL_AND_VERIFY.txt").is_file()
