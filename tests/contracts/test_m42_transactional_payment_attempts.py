"""Contract and migration gates for M4.2 transactional payment attempts."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.payment_attempt_contract import (
    CONTRACT_CODE,
    CreatePaymentAttemptCommand,
    PaymentAttemptValidationError,
    TransitionPaymentAttemptCommand,
)
from core.persistence.m42_payment_attempts import (
    FORBIDDEN_SIDE_EFFECT_TABLES,
    M42_COLUMNS,
    M42_TABLES,
    M42_TRIGGERS,
    PARENT_REVISION,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)

CONTRACT = json.loads(
    (ROOT / "contracts/finance/v1/m42_transactional_payment_attempts.json").read_text(encoding="utf-8")
)
UP_SQL = (ROOT / "alembic_neutral/sql/m42_payment_attempts_up.sql").read_text(encoding="utf-8")
DOWN_SQL = (ROOT / "alembic_neutral/sql/m42_payment_attempts_down.sql").read_text(encoding="utf-8")
VERSION_SOURCE = (
    ROOT / "alembic_neutral/versions/m42_payment_attempts_012_transactional_attempt_history.py"
).read_text(encoding="utf-8")
CONTRACT_SOURCE = (ROOT / "core/domain/finance/payment_attempt_contract.py").read_text(encoding="utf-8")
REPOSITORY_SOURCE = (ROOT / "core/domain/finance/payment_attempt_repository.py").read_text(encoding="utf-8")
ENGINE_SOURCE = (ROOT / "core/domain/finance/payment_attempt_engine.py").read_text(encoding="utf-8")
VERIFIER_SOURCE = (ROOT / "scripts/verify_m42_payment_attempts.py").read_text(encoding="utf-8")

BASE = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def create_command(**changes) -> CreatePaymentAttemptCommand:
    values = dict(
        public_id=UUID("42000000-0000-0000-0000-000000000101"),
        tenant_id=1,
        organization_unit_id=2,
        payment_intent_public_id=UUID("42000000-0000-0000-0000-000000000001"),
        attempted_amount=Decimal("100"),
        currency_code="XAF",
        payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",
        orchestrator_code="xbos_direct",
        provider_account_public_id=UUID("42000000-0000-0000-0000-000000000010"),
        underlying_provider_code="mtn_momo",
        timeout_at=BASE + timedelta(minutes=5),
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("42000000-0000-0000-0000-000000000002"),
        actor_service="contracts",
        source_component="m42.tests",
        source_record_id="attempt-1",
        idempotency_scope="m42.attempt",
        idempotency_key="attempt-1",
        metadata={"channel": "contract"},
    )
    values.update(changes)
    return CreatePaymentAttemptCommand(**values)


def transition_command(**changes) -> TransitionPaymentAttemptCommand:
    values = dict(
        tenant_id=1,
        organization_unit_id=2,
        payment_attempt_public_id=UUID("42000000-0000-0000-0000-000000000101"),
        expected_row_version=2,
        target_state="failed",
        reason_code="provider_declined",
        failure_code="provider_declined",
        external_attempt_reference="mtn-ref-001",
        evidence_payload={"code": "51"},
        occurred_at=BASE + timedelta(minutes=1),
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("42000000-0000-0000-0000-000000000002"),
        actor_service="contracts",
        source_component="m42.tests",
        source_record_id="attempt-1-failed",
        idempotency_scope="m42.transition",
        idempotency_key="attempt-1-failed",
    )
    values.update(changes)
    return TransitionPaymentAttemptCommand(**values)


def raises_code(code: str, constructor, **changes) -> None:
    with pytest.raises(PaymentAttemptValidationError) as caught:
        constructor(**changes)
    assert caught.value.code == code


def test_contract_identity_parent_and_target() -> None:
    assert CONTRACT["contract_code"] == CONTRACT_CODE
    assert CONTRACT["parent_checkpoint"] == {
        "commit": "299f0b9",
        "migration_revision": PARENT_REVISION,
    }
    assert CONTRACT["target_revision"] == TARGET_REVISION


def test_migration_is_one_linear_revision() -> None:
    assert 'revision = "m42_payment_attempts_012"' in VERSION_SOURCE
    assert 'down_revision = "m40_payment_foundation_011"' in VERSION_SOURCE
    assert VERSION_SOURCE.count("def upgrade") == 1
    assert VERSION_SOURCE.count("def downgrade") == 1


def test_migration_adds_only_attempt_capacity() -> None:
    assert M42_TABLES == ("canonical_payment_attempt_transitions",)
    for column in M42_COLUMNS:
        assert f"ADD COLUMN {column}" in UP_SQL
    assert "CREATE TABLE public.canonical_payment_attempt_transitions" in UP_SQL
    assert "CREATE TABLE public.payment_settlements" not in UP_SQL
    assert "CREATE TABLE public.canonical_payment_tenders" not in UP_SQL


def test_migration_has_all_governance_triggers() -> None:
    for trigger in M42_TRIGGERS:
        assert trigger in UP_SQL
        assert f"DROP TRIGGER IF EXISTS {trigger}" in DOWN_SQL


def test_transition_history_is_append_only_and_transaction_consistent() -> None:
    assert "xbos_reject_immutable_payment_evidence" in UP_SQL
    assert "DEFERRABLE INITIALLY DEFERRED" in UP_SQL
    assert "payment attempt state and append-only history diverge" in UP_SQL


def test_database_blocks_ungoverned_attempt_update_and_delete() -> None:
    assert "payment attempt update lacks matching append-only transition evidence" in UP_SQL
    assert "payment attempt identity and routing fields are immutable" in UP_SQL
    assert "trg_payment_attempt_reject_delete" in UP_SQL


def test_database_validates_retry_and_timeout() -> None:
    assert "retry must follow a terminal unsuccessful attempt for the same intent" in UP_SQL
    assert "payment attempt cannot expire before its timeout authority" in UP_SQL
    assert "fk_canonical_payment_attempts_retry" in UP_SQL


def test_unbound_external_reference_has_deterministic_uniqueness() -> None:
    assert "uq_canonical_payment_attempts_unbound_external" in UP_SQL
    assert "tenant_id, orchestrator_code, external_attempt_reference" in UP_SQL


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "1.000000001", "10000000000000000"])
def test_create_rejects_invalid_money(amount: str) -> None:
    raises_code("invalid_money", create_command, attempted_amount=amount)


def test_create_normalizes_routing_and_currency() -> None:
    command = create_command(
        currency_code="xaf",
        payment_method_code=" Mobile_Money ",
        payment_rail_code=" MTN_MOMO ",
        orchestrator_code=" XBOS_DIRECT ",
    )
    assert command.currency_code == "XAF"
    assert command.payment_method_code == "mobile_money"
    assert command.payment_rail_code == "mtn_momo"
    assert command.orchestrator_code == "xbos_direct"


def test_create_requires_provider_account_for_underlying_provider() -> None:
    raises_code(
        "provider_account_required",
        create_command,
        provider_account_public_id=None,
        underlying_provider_code="mtn_momo",
    )


def test_create_allows_provider_neutral_unbound_attempt() -> None:
    command = create_command(provider_account_public_id=None, underlying_provider_code=None)
    assert command.provider_account_public_id is None
    assert command.underlying_provider_code is None


def test_create_requires_timezone_aware_occurrence_and_timeout() -> None:
    raises_code("timezone_required", create_command, occurred_at=datetime(2026, 8, 9, 12, 0))
    raises_code("timezone_required", create_command, timeout_at=datetime(2026, 8, 9, 12, 5))


def test_create_rejects_timeout_not_after_occurrence() -> None:
    raises_code("invalid_timeout", create_command, timeout_at=BASE)


def test_create_rejects_blank_or_oversized_external_reference() -> None:
    raises_code("empty_external_reference", create_command, external_attempt_reference="  ")
    raises_code("external_reference_too_long", create_command, external_attempt_reference="x" * 256)


def test_create_fingerprint_is_canonical_and_sensitive() -> None:
    first = create_command(metadata={"a": 1, "b": 2})
    reordered = create_command(metadata={"b": 2, "a": 1})
    changed = replace(first, payment_rail_code="orange_money")
    assert first.request_fingerprint == reordered.request_fingerprint
    assert first.request_fingerprint != changed.request_fingerprint
    assert len(first.request_fingerprint) == 64


def test_create_rejects_oversized_source_identity_for_initial_history_suffix() -> None:
    raises_code("command_identity_too_long", create_command, source_record_id="x" * 192)


@pytest.mark.parametrize("state", ["pending", "unknown", "partially_succeeded"])
def test_transition_rejects_invalid_target(state: str) -> None:
    raises_code("invalid_attempt_target_state", transition_command, target_state=state)


def test_failed_transition_requires_failure_code() -> None:
    raises_code("failure_code_required", transition_command, failure_code=None)


def test_nonfailed_transition_rejects_failure_code() -> None:
    raises_code(
        "unexpected_failure_code",
        transition_command,
        target_state="succeeded",
        failure_code="declined",
    )


@pytest.mark.parametrize("state", ["succeeded", "failed", "expired"])
def test_result_transitions_require_evidence(state: str) -> None:
    changes = {"target_state": state, "evidence_payload": {}}
    if state == "failed":
        changes["failure_code"] = "declined"
    else:
        changes["failure_code"] = None
    raises_code("terminal_evidence_required", transition_command, **changes)


def test_cancel_can_use_operator_reason_without_provider_evidence() -> None:
    command = transition_command(
        target_state="cancelled",
        failure_code=None,
        evidence_payload={},
    )
    assert command.target_state == "cancelled"


def test_repository_uses_existing_attempt_table_and_new_history_table() -> None:
    assert "INSERT INTO public.canonical_payment_attempts" in REPOSITORY_SOURCE
    assert "INSERT INTO public.canonical_payment_attempt_transitions" in REPOSITORY_SOURCE
    assert "payment_tender_id" in REPOSITORY_SOURCE
    assert "NULL, :provider_account_id" in REPOSITORY_SOURCE


def test_repository_updates_state_only_after_append_only_transition() -> None:
    assert ENGINE_SOURCE.index("insert_transition") < ENGINE_SOURCE.index("apply_transition")
    assert "row_version=row_version + 1" in REPOSITORY_SOURCE
    assert "expected_row_version" in REPOSITORY_SOURCE


def test_engine_enforces_intent_amount_method_scope_currency_and_expiry() -> None:
    for code in (
        "payment_intent_not_found",
        "payment_intent_scope_mismatch",
        "payment_intent_currency_mismatch",
        "payment_intent_not_attemptable",
        "payment_intent_expired",
        "attempt_amount_exceeds_intent",
        "payment_method_not_allowed",
    ):
        assert code in ENGINE_SOURCE


def test_engine_enforces_provider_account_authority() -> None:
    for code in (
        "provider_account_unavailable",
        "provider_account_scope_mismatch",
        "provider_account_code_mismatch",
    ):
        assert code in ENGINE_SOURCE


def test_engine_preserves_terminal_attempt_and_creates_retry_as_new_row() -> None:
    assert "retry_of_attempt_public_id" in ENGINE_SOURCE
    assert "retry_not_allowed" in ENGINE_SOURCE
    assert "insert_attempt" in ENGINE_SOURCE
    assert "UPDATE public.canonical_payment_attempts" in REPOSITORY_SOURCE
    assert "retry_of_attempt_id" not in REPOSITORY_SOURCE.split("UPDATE public.canonical_payment_attempts", 1)[1]


def test_engine_rejects_reference_rewrite_timeout_and_terminal_transition() -> None:
    assert "external_reference_conflict" in ENGINE_SOURCE
    assert "attempt_timeout_not_reached" in ENGINE_SOURCE
    assert '"succeeded": set()' in ENGINE_SOURCE
    assert '"failed": set()' in ENGINE_SOURCE


def test_transition_replay_uses_historical_transition_snapshot() -> None:
    assert 'snapshot.get("transition_public_id")' in ENGINE_SOURCE
    assert "find_transition" in ENGINE_SOURCE
    assert '"transition_public_id": str(transition.public_id)' in ENGINE_SOURCE


def test_verifier_requires_clean_parent_and_applies_migration_only_to_disposable() -> None:
    assert f'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"' in VERIFIER_SOURCE
    assert "development must start at" in VERIFIER_SOURCE
    assert "_migrate(TEST_DATABASE_NAME, TARGET_REVISION)" in VERIFIER_SOURCE
    assert "_migrate(DEVELOPMENT_DATABASE_NAME" not in VERIFIER_SOURCE


def test_verifier_proves_all_m42_acceptance_cases() -> None:
    for marker in (
        "attempt creation replay failed",
        "attempt creation conflict was accepted",
        "attempt transition replay failed",
        "attempt expired before timeout",
        "external attempt reference was rewritten",
        "failed attempt evidence was not preserved",
        "cross-tenant attempt lookup succeeded",
        "direct SQL bypass succeeded",
    ):
        assert marker in VERIFIER_SOURCE


def test_verifier_has_exact_disposable_target_and_no_downstream_side_effects() -> None:
    assert TEST_DATABASE_NAME == "xbos_track_b_m42_attempts_test"
    assert "side_effects=0" in VERIFIER_SOURCE
    assert set(FORBIDDEN_SIDE_EFFECT_TABLES) >= {
        "canonical_payment_tenders",
        "provider_callback_events",
        "payment_settlements",
        "payment_settlement_reversals",
        "value_sources",
        "financial_events",
        "outbox_messages",
    }


def test_m42_does_not_call_provider_create_settlement_or_switch_writer() -> None:
    lowered = (CONTRACT_SOURCE + REPOSITORY_SOURCE + ENGINE_SOURCE).lower()
    assert "provider_adapter" not in lowered
    assert "insert into public.payment_settlements" not in lowered
    assert "insert into public.provider_callback_events" not in lowered
    assert "wnd" not in lowered
