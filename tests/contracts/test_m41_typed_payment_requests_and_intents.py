"""Contract gates for M4.1 typed payment requests and intents."""

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

from core.domain.finance.payment_intent_contract import (
    CONTRACT_CODE,
    CreatePaymentIntentCommand,
    CreatePaymentRequestCommand,
    PaymentCommandValidationError,
    normalize_method_policy,
)
from core.persistence.m41_payment_commands import (
    FORBIDDEN_SIDE_EFFECT_TABLES,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
    WRITTEN_TABLES,
)

CONTRACT_PATH = ROOT / "contracts/finance/v1/m41_typed_payment_requests_and_intents.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
CONTRACT_SOURCE = (ROOT / "core/domain/finance/payment_intent_contract.py").read_text(encoding="utf-8")
REPOSITORY_SOURCE = (ROOT / "core/domain/finance/payment_intent_repository.py").read_text(encoding="utf-8")
ENGINE_SOURCE = (ROOT / "core/domain/finance/payment_intent_engine.py").read_text(encoding="utf-8")
VERIFIER_SOURCE = (ROOT / "scripts/verify_m41_payment_commands.py").read_text(encoding="utf-8")

BASE = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def request_command(**changes) -> CreatePaymentRequestCommand:
    values = dict(
        public_id=UUID("41000000-0000-0000-0000-000000000001"),
        tenant_id=1,
        organization_unit_id=2,
        payer_party_id=UUID("41000000-0000-0000-0000-000000000002"),
        purpose_code="invoice.collection",
        requested_amount=Decimal("100"),
        currency_code="XAF",
        expires_at=BASE + timedelta(days=1),
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("41000000-0000-0000-0000-000000000003"),
        actor_service="contracts",
        source_component="m41.tests",
        source_record_id="request-1",
        idempotency_scope="m41.request",
        idempotency_key="request-1",
        metadata={"channel": "contract"},
    )
    values.update(changes)
    return CreatePaymentRequestCommand(**values)


def intent_command(**changes) -> CreatePaymentIntentCommand:
    values = dict(
        public_id=UUID("41000000-0000-0000-0000-000000000011"),
        tenant_id=1,
        organization_unit_id=2,
        requested_amount=Decimal("40"),
        currency_code="XAF",
        payment_method_policy={
            "allowed_methods": ["cash", "mobile_money"],
            "allow_mixed_tender": True,
            "max_tenders": 2,
        },
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("41000000-0000-0000-0000-000000000003"),
        actor_service="contracts",
        source_component="m41.tests",
        source_record_id="intent-1",
        idempotency_scope="m41.intent",
        idempotency_key="intent-1",
        metadata={},
    )
    values.update(changes)
    return CreatePaymentIntentCommand(**values)


def raises_code(code: str, constructor, **changes) -> None:
    with pytest.raises(PaymentCommandValidationError) as caught:
        constructor(**changes)
    assert caught.value.code == code


def test_contract_identity_and_parent_checkpoint() -> None:
    assert CONTRACT["contract_code"] == CONTRACT_CODE
    assert CONTRACT["parent_checkpoint"] == {
        "commit": "f31dc2f",
        "migration_revision": TARGET_REVISION,
    }


def test_m41_is_schema_neutral_and_preserves_canonical_head() -> None:
    assert CONTRACT["schema_change"] is False
    assert TARGET_REVISION == "m40_payment_foundation_011"
    assert not list((ROOT / "alembic_neutral/versions").glob("*m41*"))


def test_contract_defers_execution_and_writer_cutover() -> None:
    assert CONTRACT["scope"]["calls_provider"] is False
    assert CONTRACT["scope"]["creates_tenders"] is False
    assert CONTRACT["scope"]["creates_attempts"] is False
    assert CONTRACT["scope"]["creates_settlements"] is False
    assert CONTRACT["scope"]["activates_wnd_writer"] is False
    assert CONTRACT["scope"]["adds_public_routes"] is False


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1.000000001", "10000000000000000"])
def test_request_rejects_invalid_money(amount: str) -> None:
    raises_code("invalid_money", request_command, requested_amount=amount)


def test_request_normalizes_money_currency_and_purpose() -> None:
    command = request_command(requested_amount="10.5", currency_code="xaf", purpose_code=" Invoice.Collection ")
    assert command.requested_amount == Decimal("10.50000000")
    assert command.currency_code == "XAF"
    assert command.purpose_code == "invoice.collection"


def test_request_requires_timezone_aware_occurrence() -> None:
    raises_code("timezone_required", request_command, occurred_at=datetime(2026, 8, 9, 12, 0))


def test_request_requires_expiry_after_occurrence() -> None:
    raises_code("invalid_expiry", request_command, expires_at=BASE)


@pytest.mark.parametrize("changes", [{"tenant_id": 0}, {"organization_unit_id": 0}])
def test_commands_require_positive_scope(changes) -> None:
    raises_code("invalid_scope", request_command, **changes)


def test_commands_require_an_actor() -> None:
    raises_code("actor_required", request_command, actor_service=None, actor_user_id=None)


def test_commands_require_source_and_idempotency_identity() -> None:
    raises_code("missing_command_identity", request_command, idempotency_key="  ")


def test_metadata_must_be_json_serializable() -> None:
    raises_code("invalid_json_value", request_command, metadata={"bad": object()})


def test_request_fingerprint_is_canonical_and_sensitive() -> None:
    first = request_command(metadata={"a": 1, "b": 2})
    reordered = request_command(metadata={"b": 2, "a": 1})
    changed = replace(first, requested_amount=Decimal("101"))
    assert first.request_fingerprint == reordered.request_fingerprint
    assert first.request_fingerprint != changed.request_fingerprint
    assert len(first.request_fingerprint) == 64


def test_method_policy_normalizes_provider_neutral_methods() -> None:
    assert normalize_method_policy({"allowed_methods": [" CASH "], "max_tenders": 1}) == {
        "allowed_methods": ["cash"],
        "allow_mixed_tender": False,
        "max_tenders": 1,
    }


@pytest.mark.parametrize("key", ["provider", "rail", "provider_account", "orchestrator"])
def test_method_policy_rejects_provider_coupling(key: str) -> None:
    raises_code(
        "provider_coupling_forbidden",
        intent_command,
        payment_method_policy={"allowed_methods": ["cash"], key: "vendor"},
    )


def test_method_policy_requires_nonempty_methods() -> None:
    raises_code("methods_required", intent_command, payment_method_policy={"allowed_methods": []})


def test_method_policy_rejects_duplicate_methods() -> None:
    raises_code(
        "duplicate_payment_method",
        intent_command,
        payment_method_policy={"allowed_methods": ["cash", "cash"]},
    )


@pytest.mark.parametrize("maximum", [0, 17, True, "2"])
def test_method_policy_bounds_tender_count(maximum) -> None:
    raises_code(
        "invalid_max_tenders",
        intent_command,
        payment_method_policy={"allowed_methods": ["cash"], "max_tenders": maximum},
    )


def test_method_policy_requires_one_tender_when_mixing_is_disabled() -> None:
    raises_code(
        "inconsistent_mixed_tender_policy",
        intent_command,
        payment_method_policy={"allowed_methods": ["cash"], "max_tenders": 2},
    )


def test_intent_origin_is_standalone_without_fake_link() -> None:
    command = intent_command()
    assert command.intent_origin == "standalone"
    assert command.canonical_payload()["payment_request_public_id"] is None
    assert command.canonical_payload()["financial_obligation_public_id"] is None


def test_intent_origin_can_be_payment_request() -> None:
    command = intent_command(payment_request_public_id=UUID("41000000-0000-0000-0000-000000000001"))
    assert command.intent_origin == "payment_request"


def test_intent_origin_can_be_financial_obligation() -> None:
    command = intent_command(financial_obligation_public_id=UUID("41000000-0000-0000-0000-000000000021"))
    assert command.intent_origin == "financial_obligation"


def test_intent_rejects_ambiguous_origin() -> None:
    raises_code(
        "ambiguous_intent_origin",
        intent_command,
        payment_request_public_id=UUID("41000000-0000-0000-0000-000000000001"),
        financial_obligation_public_id=UUID("41000000-0000-0000-0000-000000000021"),
    )


def test_repository_writes_only_approved_tables() -> None:
    assert WRITTEN_TABLES == (
        "canonical_payment_requests",
        "canonical_payment_intents",
        "idempotency_records",
    )
    for table in WRITTEN_TABLES:
        assert table in REPOSITORY_SOURCE
    for table in ("payments", "payment_attempts", "payment_settlements"):
        assert f"INSERT INTO public.{table} " not in REPOSITORY_SOURCE


def test_repository_uses_shared_atomic_idempotency_authority() -> None:
    assert "INSERT INTO public.idempotency_records" in REPOSITORY_SOURCE
    assert "request_fingerprint" in REPOSITORY_SOURCE
    assert "session.begin_nested()" in REPOSITORY_SOURCE
    assert "PaymentCommandIdempotencyConflict" in REPOSITORY_SOURCE


def test_engine_locks_and_caps_payment_request() -> None:
    assert "lock=True" in ENGINE_SOURCE
    assert "payment_request_capacity_exceeded" in ENGINE_SOURCE
    assert "requested_amount - request.committed_intent_amount" in ENGINE_SOURCE


def test_engine_validates_obligation_scope_currency_state_and_balance() -> None:
    for code in (
        "financial_obligation_not_found",
        "financial_obligation_scope_mismatch",
        "financial_obligation_currency_mismatch",
        "financial_obligation_not_collectible",
        "financial_obligation_capacity_exceeded",
    ):
        assert code in ENGINE_SOURCE
    assert "balance_service.get" in ENGINE_SOURCE


def test_engine_has_no_provider_or_legacy_service_dependency() -> None:
    lowered = ENGINE_SOURCE.lower()
    assert "provider_adapter" not in lowered
    assert "paymentservice" not in ENGINE_SOURCE
    assert "legacy" not in lowered


def test_forbidden_side_effect_inventory_is_complete() -> None:
    assert set(FORBIDDEN_SIDE_EFFECT_TABLES) >= {
        "canonical_payment_tenders",
        "canonical_payment_attempts",
        "provider_callback_events",
        "payment_settlements",
        "payment_settlement_reversals",
        "value_sources",
        "financial_events",
        "outbox_messages",
    }


def test_verifier_is_read_only_against_development_and_disposable_for_writes() -> None:
    assert f'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"' in VERIFIER_SOURCE
    assert f'TEST_DATABASE_NAME = "{TEST_DATABASE_NAME}"' not in VERIFIER_SOURCE  # imported policy
    assert 'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"' in VERIFIER_SOURCE
    assert "_exercise(disposable)" in VERIFIER_SOURCE
    assert "_exercise(application_engine)" not in VERIFIER_SOURCE


def test_verifier_proves_replay_conflict_capacity_rollback_and_zero_side_effects() -> None:
    for marker in (
        "payment request replay semantics failed",
        "payment request idempotency conflict was accepted",
        "payment request over-capacity intent was accepted",
        "obligation-linked intent lost its origin authority",
        "failed command retained its idempotency reservation",
        "M4.1 created forbidden side effects",
    ):
        assert marker in VERIFIER_SOURCE
