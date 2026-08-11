from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.reconciliation_calendar_service import ReconciliationCalendarService
from core.domain.finance.reconciliation_window_contract import (
    CASCADE_REASONS,
    CascadeReconciliationWindowsCommand,
    CreateReconciliationCalendarPolicyCommand,
    CreateReconciliationSeriesCommand,
    RecordReconciliationWindowCommand,
    ReconciliationWindowValidationError,
    ShiftDefinition,
)
from core.domain.finance.reconciliation_window_repository import CalendarPolicyRecord

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m62_reconciliation_windows_continuity_and_cascades.json"
UP = ROOT / "alembic_neutral/sql/m62_reconciliation_windows_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m62_reconciliation_windows_down.sql"
MIGRATION = ROOT / "alembic_neutral/versions/m62_reconciliation_windows_018_continuity_calendar_and_cascades.py"
ENGINE = ROOT / "core/domain/finance/reconciliation_window_engine.py"
REPOSITORY = ROOT / "core/domain/finance/reconciliation_window_repository.py"
BASE = datetime(2026, 8, 10, 7, tzinfo=timezone.utc)
CORRELATION = UUID("62000000-0000-0000-0000-000000000099")
POLICY_PUBLIC = UUID("62000000-0000-0000-0000-000000000001")
ACCOUNT_PUBLIC = UUID("62000000-0000-0000-0000-000000000002")
SERIES_PUBLIC = UUID("62000000-0000-0000-0000-000000000003")


def policy_command(**changes):
    values = dict(
        public_id=POLICY_PUBLIC, tenant_id=2, organization_unit_id=3, policy_code="shift-calendar",
        policy_version=1, timezone_name="Africa/Douala", business_day_boundary="08:00",
        shifts=(ShiftDefinition("day", "08:00"), ShiftDefinition("night", "18:00")),
        effective_from=BASE-timedelta(days=1), occurred_at=BASE, business_date=date(2026, 8, 10),
        calendar_policy_version=1, correlation_id=CORRELATION, source_component="m62.verifier",
        source_record_id="policy", idempotency_scope="m62.policy", idempotency_key="policy",
        actor_service="m62.verifier",
    )
    values.update(changes)
    return CreateReconciliationCalendarPolicyCommand(**values)


def series_command(**changes):
    values = dict(
        public_id=SERIES_PUBLIC, tenant_id=2, organization_unit_id=3,
        operational_account_public_id=ACCOUNT_PUBLIC, calendar_policy_public_id=POLICY_PUBLIC,
        series_code="drawer-shifts", currency_code="xaf", starts_at=BASE,
        occurred_at=BASE, business_date=date(2026, 8, 10), calendar_policy_version=1,
        correlation_id=CORRELATION, source_component="m62.verifier", source_record_id="series",
        idempotency_scope="m62.series", idempotency_key="series", actor_service="m62.verifier",
    )
    values.update(changes)
    return CreateReconciliationSeriesCommand(**values)


def window_command(**changes):
    values = dict(
        public_id=UUID("62000000-0000-0000-0001-000000000001"), tenant_id=2, organization_unit_id=3,
        reconciliation_series_public_id=SERIES_PUBLIC, window_start=BASE, window_end=BASE+timedelta(hours=10),
        evidence_payload={"count_sheet": "day"}, occurred_at=BASE+timedelta(hours=10),
        business_date=date(2026, 8, 10), calendar_policy_version=1, correlation_id=CORRELATION,
        source_component="m62.verifier", source_record_id="window-1", idempotency_scope="m62.window",
        idempotency_key="window-1", actor_service="m62.verifier",
    )
    values.update(changes)
    return RecordReconciliationWindowCommand(**values)


def cascade_command(**changes):
    values = dict(
        public_id=UUID("62000000-0000-0000-0002-000000000001"), tenant_id=2, organization_unit_id=3,
        reconciliation_series_public_id=SERIES_PUBLIC, changed_from_at=BASE+timedelta(hours=1),
        cascade_reason="financial_fact_appended", evidence_payload={"correction": "approved"},
        occurred_at=BASE+timedelta(days=1), business_date=date(2026, 8, 11), calendar_policy_version=1,
        correlation_id=CORRELATION, source_component="m62.verifier", source_record_id="cascade",
        idempotency_scope="m62.cascade", idempotency_key="cascade", actor_service="m62.verifier",
    )
    values.update(changes)
    return CascadeReconciliationWindowsCommand(**values)


def stored_policy():
    command = policy_command()
    return CalendarPolicyRecord(
        1, command.public_id, 2, 3, command.policy_code, 1, command.timezone_name,
        command.business_day_boundary, tuple(item.canonical_payload() for item in command.shifts),
        command.effective_from, command.request_fingerprint,
    )


def test_contract_scope_and_deferred_close_are_frozen():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["window_authority"]["formal_close_state"] is False
    assert "formal_close" in data["deferred_to_m63_plus"]
    assert data["correction_cascade"]["financial_events_are_never_rewritten"] is True


def test_migration_is_linear_and_raw_dbapi_safe():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "m62_reconciliation_windows_018"' in source
    assert 'down_revision = "m61_transfers_reconciliation_017"' in source
    assert "op.get_bind().connection.cursor()" in source and "exec_driver_sql" not in source


def test_schema_installs_all_m62_authorities():
    source = UP.read_text(encoding="utf-8")
    for table in (
        "reconciliation_calendar_policies", "reconciliation_series", "reconciliation_windows",
        "reconciliation_cascade_runs", "reconciliation_window_revisions",
    ):
        assert f"CREATE TABLE public.{table}" in source
    assert "CREATE VIEW public.current_reconciliation_window_revisions" in source
    assert "actual_provenance" in source and "actual_evidence_hash" in source


def test_database_enforces_continuity_and_revision_order():
    source = UP.read_text(encoding="utf-8")
    assert "xbos_validate_reconciliation_window_continuity" in source
    assert "NEW.window_start<>latest.window_end" in source
    assert "NEW.predecessor_window_id IS DISTINCT FROM latest.id" in source
    assert "xbos_validate_reconciliation_revision_sequence" in source
    assert "NEW.revision_number<>latest.revision_number+1" in source


def test_database_preserves_append_only_truth():
    source = UP.read_text(encoding="utf-8")
    assert "xbos_reject_reconciliation_fact_mutation" in source
    assert source.count("immutable BEFORE UPDATE OR DELETE") == 5
    assert "supersedes_revision_id" in source and "cascade_run_id" in source


def test_down_removes_only_m62_objects_in_dependency_order():
    source = DOWN.read_text(encoding="utf-8")
    assert source.index("DROP TABLE IF EXISTS public.reconciliation_window_revisions") < source.index("DROP TABLE IF EXISTS public.reconciliation_windows")
    assert "DROP TABLE IF EXISTS public.financial_events" not in source
    assert "DROP TABLE IF EXISTS public.operational_financial_accounts" not in source


def test_engine_reuses_m60_projection_and_never_writes_financial_truth():
    source = ENGINE.read_text(encoding="utf-8")
    assert "balance_repository.position" in source
    assert "actual_in_window" in source
    assert "INSERT INTO financial_events" not in source
    assert "UPDATE financial_events" not in source


def test_repository_is_tenant_scoped_and_locks_ordered_successors():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "tenant_id=:tenant" in source
    assert "ORDER BY window_start,id FOR UPDATE" in source
    assert "ORDER BY revision_number DESC LIMIT 1" in source


def test_calendar_policy_normalizes_and_fingerprints():
    command = policy_command()
    assert command.business_day_boundary == time(8)
    assert [item.code for item in command.shifts] == ["day", "night"]
    assert command.request_fingerprint == policy_command().request_fingerprint


@pytest.mark.parametrize("changes,code", [
    ({"timezone_name": "Mars/Olympus"}, "invalid_timezone"),
    ({"business_day_boundary": "08:00", "shifts": (ShiftDefinition("night", "18:00"),)}, "boundary_shift_required"),
    ({"shifts": (ShiftDefinition("day", "08:00"), ShiftDefinition("day", "18:00"))}, "duplicate_shift"),
    ({"policy_version": 0}, "invalid_policy_version"),
])
def test_invalid_calendar_policy_rejected(changes, code):
    with pytest.raises(ReconciliationWindowValidationError) as raised:
        policy_command(**changes)
    assert raised.value.code == code


def test_business_date_and_shift_wrap_before_boundary():
    policy = stored_policy()
    before_boundary = datetime(2026, 8, 10, 6, tzinfo=timezone.utc)  # 07:00 local
    attribution = ReconciliationCalendarService.attribute(policy, before_boundary)
    assert attribution.business_date == date(2026, 8, 9)
    assert attribution.shift_code == "night"


def test_day_window_is_exactly_next_shift_boundary():
    result = ReconciliationCalendarService.validate_window(stored_policy(), BASE, BASE+timedelta(hours=10))
    assert result.business_date == date(2026, 8, 10) and result.shift_code == "day"


def test_night_window_wraps_to_next_business_boundary():
    start = BASE+timedelta(hours=10)
    end = BASE+timedelta(days=1)
    result = ReconciliationCalendarService.validate_window(stored_policy(), start, end)
    assert result.business_date == date(2026, 8, 10) and result.shift_code == "night"


@pytest.mark.parametrize("start,end,code", [
    (BASE+timedelta(hours=1), BASE+timedelta(hours=10), "window_not_shift_aligned"),
    (BASE, BASE+timedelta(hours=9), "window_end_mismatch"),
])
def test_misaligned_window_rejected(start, end, code):
    with pytest.raises(ReconciliationWindowValidationError) as raised:
        ReconciliationCalendarService.validate_window(stored_policy(), start, end)
    assert raised.value.code == code


def test_series_normalizes_currency_and_identity():
    command = series_command()
    assert command.currency_code == "XAF" and command.operational_account_public_id == ACCOUNT_PUBLIC


def test_invalid_window_range_and_empty_evidence_rejected():
    with pytest.raises(ReconciliationWindowValidationError) as raised:
        window_command(window_end=BASE)
    assert raised.value.code == "invalid_window_range"
    with pytest.raises(ReconciliationWindowValidationError) as raised:
        window_command(evidence_payload={})
    assert raised.value.code == "evidence_required"


@pytest.mark.parametrize("reason", sorted(CASCADE_REASONS))
def test_approved_cascade_reasons(reason):
    assert cascade_command(cascade_reason=reason).cascade_reason == reason


def test_invalid_cascade_reason_rejected():
    with pytest.raises(ReconciliationWindowValidationError) as raised:
        cascade_command(cascade_reason="rewrite_history")
    assert raised.value.code == "invalid_cascade_reason"


def test_cascade_fingerprint_is_content_sensitive():
    assert cascade_command().request_fingerprint != cascade_command(changed_from_at=BASE).request_fingerprint


def test_no_wnd_or_close_semantics_leak_into_implementation():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (UP, ENGINE, REPOSITORY))
    assert "WND" not in combined and "6 p.m." not in combined
    assert "close_reconciliation_window" not in combined and "period_state" not in combined


def test_persistent_verifier_is_present():
    assert (ROOT / "scripts/verify_m62_reconciliation_windows.py").is_file()
