import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "contracts" / "finance" / "v1" / "financial_event_catalog.json"
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m21_canonical_event_engine.json"
ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "event_engine.py"
REPOSITORY_PATH = ROOT / "core" / "domain" / "finance" / "event_repository.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m21_canonical_event_engine.py"

from core.domain.finance.event_contract import (
    ENGINE_CONTRACT,
    ENGINE_CONTRACT_VERSION,
    CanonicalFinancialEventCommand,
    CatalogEventPolicy,
    FinancialEventValidationError,
    canonical_command_fingerprint,
    canonical_decimal,
    validate_command_against_policy,
    validate_command_structure,
)


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def policy(catalog, event_code):
    event = next(
        event for event in catalog["event_types"]
        if event["event_type_code"] == event_code
    )
    return CatalogEventPolicy.from_event_definition(event)


def revenue_command(**overrides):
    values = {
        "public_id": UUID("10000000-0000-0000-0000-000000000001"),
        "tenant_id": 910001,
        "organization_unit_id": 920001,
        "event_type_code": "COMMERCIAL_REVENUE_RECOGNIZED",
        "event_version": 1,
        "amount": Decimal("1000.00"),
        "currency_code": "XAF",
        "economic_role": "recognition",
        "source_record_id": 930001,
        "occurred_at": datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc),
        "business_date": date(2026, 8, 7),
        "calendar_policy_version": 1,
        "idempotency_scope": "financial_event.emit",
        "idempotency_key": "m21:revenue:1",
        "correlation_id": UUID("20000000-0000-0000-0000-000000000001"),
        "classification_snapshot": {
            "revenue_nature": {"code": "food_sales"}
        },
        "posting_context": {"profile": "commercial_recognition"},
        "metadata": {"source": "neutral_fixture"},
        "actor_service": "m21-contract-test",
    }
    values.update(overrides)
    return CanonicalFinancialEventCommand(**values)


def test_contract_identity(contract):
    assert contract["contract_code"] == ENGINE_CONTRACT
    assert contract["contract_version"] == ENGINE_CONTRACT_VERSION == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_m20(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "49315ae",
        "migration_revision": "m20_event_catalog_003",
    }


def test_command_normalizes_codes_and_decimal():
    command = revenue_command(
        event_type_code=" commercial_revenue_recognized ",
        currency_code=" xaf ",
        amount="1000.000",
    )
    assert command.event_type_code == "COMMERCIAL_REVENUE_RECOGNIZED"
    assert command.currency_code == "XAF"
    assert command.amount == Decimal("1000.000")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1000.000"), "1000"),
        (Decimal("0.00"), "0"),
        (Decimal("1.2300"), "1.23"),
        (Decimal("-4.500"), "-4.5"),
    ],
)
def test_decimal_canonicalization(value, expected):
    assert canonical_decimal(value) == expected


def test_fingerprint_is_byte_stable_for_json_key_order():
    first = revenue_command(metadata={"b": 2, "a": 1})
    second = revenue_command(metadata={"a": 1, "b": 2})
    assert canonical_command_fingerprint(first) == canonical_command_fingerprint(second)


def test_fingerprint_normalizes_equivalent_decimal_scales():
    first = revenue_command(amount=Decimal("1000.0"))
    second = revenue_command(amount=Decimal("1000.000000"))
    assert canonical_command_fingerprint(first) == canonical_command_fingerprint(second)


def test_fingerprint_normalizes_equivalent_timezones():
    first = revenue_command(
        occurred_at=datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc)
    )
    second = revenue_command(
        occurred_at=datetime(
            2026, 8, 7, 10, 30, tzinfo=timezone(timedelta(hours=1))
        )
    )
    assert canonical_command_fingerprint(first) == canonical_command_fingerprint(second)


@pytest.mark.parametrize(
    ("field_name", "changed"),
    [
        ("amount", Decimal("1001")),
        ("currency_code", "USD"),
        ("economic_role", "correction"),
        ("source_record_id", 930002),
        ("idempotency_key", "m21:revenue:changed"),
        ("classification_snapshot", {"revenue_nature": {"code": "other"}}),
    ],
)
def test_material_command_change_changes_fingerprint(field_name, changed):
    original = revenue_command()
    altered = replace(original, **{field_name: changed})
    assert canonical_command_fingerprint(original) != canonical_command_fingerprint(altered)


def test_command_payload_excludes_recorded_at():
    assert "recorded_at" not in revenue_command().canonical_payload()


def test_naive_occurred_at_is_rejected():
    command = revenue_command(occurred_at=datetime(2026, 8, 7, 9, 30))
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_structure(command)
    assert error.value.code == "timezone_required"


def test_actor_is_required():
    command = revenue_command(actor_service=None, actor_user_id=None)
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_structure(command)
    assert error.value.code == "actor_required"


def test_reserved_kernel_metadata_is_rejected():
    command = revenue_command(metadata={"_kernel": {"forged": True}})
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_structure(command)
    assert error.value.code == "reserved_metadata_key"


def test_invalid_evidence_hash_is_rejected():
    command = revenue_command(evidence_hash="NOT-A-HASH")
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_structure(command)
    assert error.value.code == "invalid_evidence_hash"


@pytest.mark.parametrize("amount", ["0.000000001", "10000000000000000"])
def test_amount_must_fit_canonical_numeric_storage(amount):
    command = revenue_command(amount=amount)
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_structure(command)
    assert error.value.code == "amount_storage_overflow"


def test_revenue_command_satisfies_catalog_policy(catalog):
    command = revenue_command()
    validate_command_structure(command)
    validate_command_against_policy(
        command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
    )


def test_positive_amount_policy_is_enforced(catalog):
    command = revenue_command(amount=Decimal("0"))
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(
            command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
        )
    assert error.value.code == "amount_policy_violation"


def test_economic_role_policy_is_enforced(catalog):
    command = revenue_command(economic_role="correction")
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(
            command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
        )
    assert error.value.code == "economic_role_not_allowed"


def test_required_classification_role_is_enforced(catalog):
    command = revenue_command(classification_snapshot={})
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(
            command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
        )
    assert error.value.code == "classification_roles_missing"


def test_revenue_policy_forbids_operational_accounts(catalog):
    command = revenue_command(source_operational_account_id=940001)
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(
            command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
        )
    assert error.value.code == "accounts_forbidden"


def test_payment_settled_in_requires_target_and_forbids_source(catalog):
    payment_policy = policy(catalog, "PAYMENT_SETTLED")
    base = revenue_command(
        event_type_code="PAYMENT_SETTLED",
        economic_role="settlement_in",
        classification_snapshot={"settlement_purpose": {"code": "sale"}},
        source_record_id=930002,
    )
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(base, payment_policy)
    assert error.value.code == "operational_account_required"

    valid = replace(base, target_operational_account_id=940001)
    validate_command_against_policy(valid, payment_policy)


def test_value_transfer_requires_distinct_source_and_target(catalog):
    transfer_policy = policy(catalog, "VALUE_TRANSFERRED")
    command = revenue_command(
        event_type_code="VALUE_TRANSFERRED",
        economic_role="transfer",
        classification_snapshot={"transfer_purpose": {"code": "cash_to_bank"}},
        source_record_id=930003,
        source_operational_account_id=940001,
        target_operational_account_id=940001,
    )
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(command, transfer_policy)
    assert error.value.code == "accounts_must_differ"


def test_reversal_requires_original_event(catalog):
    reverse_policy = policy(catalog, "FINANCIAL_FACT_REVERSED")
    command = revenue_command(
        event_type_code="FINANCIAL_FACT_REVERSED",
        economic_role="correction",
        classification_snapshot={"reversal_reason": {"code": "operator_error"}},
        source_record_id=930004,
    )
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(command, reverse_policy)
    assert error.value.code == "original_event_required"


def test_non_reversal_forbids_original_event(catalog):
    command = revenue_command(original_event_id=1)
    with pytest.raises(FinancialEventValidationError) as error:
        validate_command_against_policy(
            command, policy(catalog, "COMMERCIAL_REVENUE_RECOGNIZED")
        )
    assert error.value.code == "original_event_forbidden"


def test_engine_does_not_commit_or_publish():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert ".commit(" not in source
    assert "outbox" not in source.lower()
    assert "publish" not in source.lower()


def test_repository_uses_nested_transaction_for_insert_race():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "session.begin_nested()" in source
    assert "except IntegrityError" in source
    assert ".commit(" not in source


def test_repository_never_writes_outbox_in_m21():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "INSERT INTO public.outbox_messages" not in source


def test_verifier_is_guarded_to_one_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m21_event_test"' in source
    assert "LOCAL_HOSTS" in source
    assert "--confirm-database-name" in source


def test_scope_defers_outbox_wnd_and_history(contract):
    deferred = set(contract["scope"]["deferred"])
    assert "transactional outbox message" in deferred
    assert "WND writer cutover" in deferred
    assert "historical transformation" in deferred
