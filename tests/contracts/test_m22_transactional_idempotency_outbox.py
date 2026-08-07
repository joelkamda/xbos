import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m22_transactional_idempotency_outbox.json"
UP_PATH = ROOT / "alembic_neutral" / "sql" / "m22_transactional_delivery_up.sql"
DOWN_PATH = ROOT / "alembic_neutral" / "sql" / "m22_transactional_delivery_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral" / "versions" / "m22_transactional_delivery_004_idempotency_and_outbox.py"
ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "transactional_event_engine.py"
IDEMPOTENCY_PATH = ROOT / "core" / "domain" / "finance" / "idempotency_repository.py"
OUTBOX_PATH = ROOT / "core" / "domain" / "finance" / "outbox_repository.py"
M21_ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "event_engine.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M22_TRANSACTIONAL_IDEMPOTENCY_OUTBOX"
    assert contract["contract_version"] == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_committed_m21(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "6acd76c",
        "migration_revision": "m20_event_catalog_003",
    }


def test_migration_has_one_linear_parent(contract):
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m22_transactional_delivery_004"' in source
    assert 'down_revision = "m20_event_catalog_003"' in source
    assert "branch_labels = None" in source


def test_approved_idempotency_states_replace_coarse_m1_states(contract):
    expected = {"processing", "completed", "failed_retryable", "failed_terminal"}
    assert set(contract["migration"]["idempotency_state_alignment"]) == expected
    source = UP_PATH.read_text(encoding="utf-8")
    for state in expected:
        assert f"'{state}'" in source
    assert "'failed'" not in source
    assert "'expired'" not in source


@pytest.mark.parametrize(
    "column",
    ["organization_unit_id", "topic", "message_key", "occurred_at", "recorded_at"],
)
def test_outbox_envelope_columns_are_installed(column):
    source = UP_PATH.read_text(encoding="utf-8")
    assert f"ADD COLUMN {column}" in source
    assert f"ALTER COLUMN {column} SET NOT NULL" in source


def test_outbox_logical_identity_is_database_unique():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, topic, message_key)" in source


def test_outbox_org_is_tenant_scoped():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "(tenant_id, organization_unit_id)" in source
    assert "organization_units(tenant_id, id)" in source


def test_outbox_trigger_protects_new_identity_and_envelope_columns():
    source = UP_PATH.read_text(encoding="utf-8")
    for name in ("NEW.organization_unit_id", "NEW.topic", "NEW.message_key", "NEW.occurred_at", "NEW.recorded_at"):
        assert name in source
    assert "BEFORE UPDATE OR DELETE ON public.outbox_messages" in source


def test_downgrade_restores_m1_state_constraint():
    source = DOWN_PATH.read_text(encoding="utf-8")
    assert "'processing', 'completed', 'failed', 'expired'" in source
    assert "DROP COLUMN IF EXISTS topic" in source


def test_engine_writes_all_three_authoritative_records(contract):
    assert set(contract["transaction"]["atomic_writes"]) == {
        "idempotency_records", "financial_events", "outbox_messages"
    }
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "idempotency_repository.reserve" in source
    assert "event_repository.insert" in source
    assert "outbox_repository.ensure_for_event" in source
    assert "idempotency_repository.complete" in source


def test_engine_uses_savepoint_and_never_commits_or_publishes():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "session.begin_nested()" in source
    assert ".commit(" not in source
    assert "publish(" not in source


def test_m21_engine_remains_unchanged_and_outbox_free():
    source = M21_ENGINE_PATH.read_text(encoding="utf-8")
    assert "outbox" not in source.lower()
    assert "idempotency_repository" not in source


def test_reservation_uses_approved_identity_and_row_lock():
    source = IDEMPOTENCY_PATH.read_text(encoding="utf-8")
    assert "tenant_id = :tenant_id" in source
    assert "scope = :scope" in source
    assert "idempotency_key = :idempotency_key" in source
    assert "FOR UPDATE" in source


def test_reservation_handles_insert_race_without_outer_rollback():
    source = IDEMPOTENCY_PATH.read_text(encoding="utf-8")
    assert "session.begin_nested()" in source
    assert "except IntegrityError" in source
    assert ".rollback(" not in source


@pytest.mark.parametrize(
    "state,code",
    [
        ("processing", "idempotency_in_progress"),
        ("failed_retryable", "idempotency_retry_authorization_required"),
        ("failed_terminal", "idempotency_terminal_failure"),
    ],
)
def test_noncompleted_replay_decisions_are_explicit(state, code):
    source = IDEMPOTENCY_PATH.read_text(encoding="utf-8")
    assert f'record.processing_state == "{state}"' in source
    assert f'"{code}"' in source


def test_completion_snapshot_contains_stable_public_ids():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert '"event_public_id"' in source
    assert '"outbox_message_public_id"' in source


def test_outbox_uses_approved_topic_and_pending_state():
    source = OUTBOX_PATH.read_text(encoding="utf-8")
    assert 'OUTBOX_TOPIC = "finance.financial-events.v1"' in source
    assert "'pending'" in source


def test_outbox_hashes_canonical_envelope():
    source = OUTBOX_PATH.read_text(encoding="utf-8")
    assert "hashlib.sha256(canonical_json_bytes(payload)).hexdigest()" in source


def test_outbox_insert_is_deduplicated_by_event():
    source = OUTBOX_PATH.read_text(encoding="utf-8")
    assert "find_for_event" in source
    assert "session.begin_nested()" in source
    assert "except IntegrityError" in source


def test_required_envelope_is_complete(contract):
    assert set(contract["outbox"]["required_envelope"]) == {
        "message_id", "tenant_id", "organization_unit_id", "topic",
        "event_type", "event_version", "message_key", "correlation_id",
        "causation_id", "occurred_at", "recorded_at", "payload",
    }


def test_no_dispatcher_or_broker_is_smuggled_into_m22(contract):
    assert "outbox_dispatch_worker" in contract["deferred"]
    assert "broker_publish_and_ack" in contract["deferred"]
    source = OUTBOX_PATH.read_text(encoding="utf-8")
    assert "broker" not in source.lower()
    assert "http" not in source.lower()


def test_wnd_cutover_remains_deferred(contract):
    assert contract["compatibility"]["wnd_writer_cutover"] is False
    assert "wnd_writer_cutover" in contract["deferred"]
