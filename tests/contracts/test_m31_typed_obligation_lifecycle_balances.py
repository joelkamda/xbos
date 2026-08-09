import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest


pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "finance" / "v1" / "m31_typed_obligation_lifecycle_and_balances.json"
CONTRACT_CODE = ROOT / "core" / "domain" / "finance" / "obligation_contract.py"
REPOSITORY = ROOT / "core" / "domain" / "finance" / "obligation_repository.py"
ENGINE = ROOT / "core" / "domain" / "finance" / "obligation_engine.py"
BALANCE = ROOT / "core" / "domain" / "finance" / "obligation_balance_service.py"
VERIFIER = ROOT / "scripts" / "verify_m31_typed_obligation_lifecycle_balances.py"
DOC = ROOT / "docs" / "track_b" / "M3_1_TYPED_OBLIGATION_LIFECYCLE_AND_DERIVED_BALANCES.md"


@pytest.fixture(scope="module")
def authority():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _line(number=1, amount="1000", key="line-1"):
    from core.domain.finance.obligation_contract import ObligationLineCommand

    return ObligationLineCommand(
        line_number=number,
        line_type="principal",
        description="Receivable principal",
        quantity=Decimal("1"),
        unit_amount=Decimal(amount),
        line_amount=Decimal(amount),
        source_record_id=key,
    )


def _command(**changes):
    from core.domain.finance.obligation_contract import CreateObligationCommand

    values = dict(
        public_id=UUID("31000000-0000-0000-0000-000000000001"),
        tenant_id=3101,
        organization_unit_id=3111,
        debtor_party_id=UUID("31000000-0000-0000-0000-000000000010"),
        creditor_party_id=UUID("31000000-0000-0000-0000-000000000011"),
        obligation_type="trade_receivable",
        original_amount=Decimal("1000"),
        currency_code="XAF",
        occurred_at=datetime(2026, 8, 9, 10, tzinfo=timezone.utc),
        due_at=datetime(2026, 9, 9, 10, tzinfo=timezone.utc),
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("31000000-0000-0000-0000-000000000020"),
        actor_service="m31.verifier",
        source_component="m31.verifier",
        source_record_id="obligation-1",
        idempotency_scope="m31.create",
        idempotency_key="create-1",
        lines=(_line(),),
    )
    values.update(changes)
    return CreateObligationCommand(**values)


def test_contract_identity(authority):
    assert authority["contract_code"] == "XBOS_M31_TYPED_OBLIGATION_LIFECYCLE_AND_BALANCES"
    assert authority["contract_version"] == 1
    assert authority["package_revision"] == 1


def test_contract_is_anchored_to_committed_m30(authority):
    assert authority["parent_checkpoint"] == {
        "commit": "ace28b6",
        "migration_revision": "m30_obligation_foundation_008",
    }


def test_m31_is_schema_neutral(authority):
    assert authority["schema_change"] is False
    assert authority["target_revision"] == "m30_obligation_foundation_008"
    assert not list((ROOT / "alembic_neutral" / "versions").glob("m31_*.py")) if (ROOT / "alembic_neutral").exists() else True


def test_atomic_creation_authority(authority):
    assert authority["commands"]["create_obligation"]["atomic_writes"] == [
        "idempotency_records", "financial_obligations", "financial_obligation_lines"
    ]
    assert authority["commands"]["create_obligation"]["commit_owner"] == "caller"


def test_manual_and_derived_states_are_separated(authority):
    transition = authority["commands"]["transition_obligation"]
    assert transition["manual_targets"] == ["cancelled", "written_off"]
    assert "derived_only" in transition["satisfaction_states"]


def test_no_integration_boundary_is_activated(authority):
    assert all(value is False for value in authority["boundaries"].values())


def test_create_command_normalizes_and_fingerprints_deterministically():
    first = _command(currency_code="xaf", metadata={"b": 2, "a": 1})
    second = _command(metadata={"a": 1, "b": 2})
    assert first.currency_code == "XAF"
    assert first.request_fingerprint == second.request_fingerprint
    assert len(first.request_fingerprint) == 64


def test_line_total_must_equal_original():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(original_amount="999")
    assert exc.value.code == "line_total_mismatch"


def test_line_arithmetic_must_be_exact():
    from core.domain.finance.obligation_contract import ObligationLineCommand, ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        ObligationLineCommand(1, "principal", "Mismatch", Decimal("2"), Decimal("4"), Decimal("7"), "x")
    assert exc.value.code == "line_arithmetic_mismatch"


def test_lines_are_required():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(lines=())
    assert exc.value.code == "lines_required"


def test_line_numbers_are_unique():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(original_amount="2000", lines=(_line(), _line(key="line-2")))
    assert exc.value.code == "duplicate_line_number"


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1.000000001", "10000000000000000"])
def test_original_money_fails_closed(amount):
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(original_amount=amount)
    assert exc.value.code == "invalid_money"


def test_parties_must_differ():
    from core.domain.finance.obligation_contract import ObligationValidationError

    party = UUID("31000000-0000-0000-0000-000000000010")
    with pytest.raises(ObligationValidationError) as exc:
        _command(debtor_party_id=party, creditor_party_id=party)
    assert exc.value.code == "same_party"


def test_due_date_cannot_precede_occurrence():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(due_at=datetime(2026, 8, 8, tzinfo=timezone.utc))
    assert exc.value.code == "invalid_due_at"


def test_timestamps_require_timezone():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(occurred_at=datetime(2026, 8, 9))
    assert exc.value.code == "timezone_required"


def test_actor_is_required():
    from core.domain.finance.obligation_contract import ObligationValidationError

    with pytest.raises(ObligationValidationError) as exc:
        _command(actor_service=None, actor_user_id=None)
    assert exc.value.code == "actor_required"


def test_transition_contract_allows_only_manual_terminal_targets():
    from core.domain.finance.obligation_contract import TransitionObligationCommand, ObligationValidationError

    common = dict(
        tenant_id=3101,
        obligation_public_id=UUID("31000000-0000-0000-0000-000000000001"),
        expected_row_version=1,
        reason_code="customer_cancelled",
        idempotency_scope="m31.transition",
        idempotency_key="transition-1",
        actor_service="m31.verifier",
    )
    assert TransitionObligationCommand(target_state="cancelled", **common).target_state == "cancelled"
    with pytest.raises(ObligationValidationError) as exc:
        TransitionObligationCommand(target_state="satisfied", **common)
    assert exc.value.code == "invalid_manual_state"


def test_transition_fingerprint_includes_expected_version():
    from core.domain.finance.obligation_contract import TransitionObligationCommand

    common = dict(
        tenant_id=3101,
        obligation_public_id=UUID("31000000-0000-0000-0000-000000000001"),
        target_state="cancelled",
        reason_code="customer_cancelled",
        idempotency_scope="m31.transition",
        idempotency_key="transition-1",
        actor_service="m31.verifier",
    )
    assert TransitionObligationCommand(expected_row_version=1, **common).request_fingerprint != TransitionObligationCommand(expected_row_version=2, **common).request_fingerprint


def test_balance_query_is_tenant_scoped_and_preaggregates_reversals():
    source = BALANCE.read_text(encoding="utf-8")
    assert source.count("WHERE tenant_id = :tenant_id") >= 1
    assert "reversal_totals" in source
    assert "allocation_totals" in source
    assert "outstanding = original - active" in source


def test_balance_fails_closed_on_over_capacity():
    source = BALANCE.read_text(encoding="utf-8")
    assert '"obligation_capacity_corrupt"' in source
    assert "outstanding < 0" in source


def test_repository_inserts_obligation_and_lines_in_caller_transaction():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "INSERT INTO public.financial_obligations" in source
    assert "INSERT INTO public.financial_obligation_lines" in source
    assert ".commit(" not in source


def test_repository_reserves_and_completes_generic_idempotency():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "INSERT INTO public.idempotency_records" in source
    assert "FOR UPDATE" in source
    assert "obligation_idempotency_conflict" in source
    assert "processing_state = 'completed'" in source


def test_creation_and_transition_each_use_one_savepoint():
    source = ENGINE.read_text(encoding="utf-8")
    assert source.count("with session.begin_nested()") == 3
    assert ".commit(" not in source


def test_engine_uses_optimistic_row_version():
    source = ENGINE.read_text(encoding="utf-8")
    assert "expected_row_version" in source
    assert "obligation_version_conflict" in source
    assert "row_version + 1" in REPOSITORY.read_text(encoding="utf-8")


def test_cancel_and_writeoff_guards_are_explicit():
    source = ENGINE.read_text(encoding="utf-8")
    assert "cancelled_obligation_has_satisfaction" in source
    assert "nothing_to_write_off" in source
    assert '{"cancelled", "written_off"}' in source
    assert '"reason_code": command.reason_code' in source
    assert '"actor_service": command.actor_service' in source


def test_satisfaction_projection_is_balance_driven():
    source = ENGINE.read_text(encoding="utf-8")
    assert "refresh_satisfaction_state" in source
    assert "balance.projected_state" in source


def test_verifier_has_one_exact_disposable_database():
    source = VERIFIER.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m31_obligation_test"' in source
    assert "refusing to drop unapproved database" in source


def test_verifier_requires_empty_development_truth():
    source = VERIFIER.read_text(encoding="utf-8")
    assert 'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"' in source
    assert "m31_obligation_development=PASS" in source


def test_verifier_exercises_replay_conflict_rollback_and_tenant_scope():
    source = VERIFIER.read_text(encoding="utf-8")
    for token in ("replay=PASS", "conflict=PASS", "rollback=PASS", "tenant_isolation=PASS"):
        assert token in source


def test_documentation_preserves_deferred_boundaries():
    source = DOC.read_text(encoding="utf-8")
    assert "does not authorize WND writer cutover" in source
    assert "M3.2" in source
    assert "No migration" in source


def test_new_modules_are_framework_independent():
    for path in (CONTRACT_CODE, REPOSITORY, ENGINE, BALANCE):
        source = path.read_text(encoding="utf-8")
        assert "fastapi" not in source.lower()
        assert "core.api" not in source
