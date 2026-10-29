"""Local synthetic WND M1 authorization/fieldset negatives, NO hosted calls."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.msar_wnd_nosecret_evidence import (
    COUNTS,
    CURRENT_SOURCE_PIN,
    DEFAULT_ENABLED,
    EXPECTED_TENANT,
    FLAGS,
    MAX_TTL,
    OFFLINE_ONLY,
    OneEventLocalLedger,
    TrustedLocalAdmission,
    evaluate_local_fake,
)

NOW = datetime(2026, 10, 29, 18, 30, tzinfo=timezone.utc)


def admission(**changes):
    values = {
        "tenant_id": EXPECTED_TENANT,
        "synthetic_scope_preapproved": True,
        "source_pin": CURRENT_SOURCE_PIN,
        "runtime_pin": CURRENT_SOURCE_PIN,
        "issuer_attested": True,
        "schema_pin_attested": True,
        "reader_acl_attested": True,
        "event_ticket": "FAKE-M1-WND-TICKET-001",
        "issued_at": NOW - timedelta(seconds=30),
        "expires_at": NOW + timedelta(seconds=60),
    }
    values.update(changes)
    return TrustedLocalAdmission(**values)


def observation(**changes):
    value = {key: True for key in FLAGS}
    value.update({key: 1 for key in COUNTS})
    value.update(changes)
    return value


def evaluate(a=None, o=None, *, at=NOW, ledger=None):
    return evaluate_local_fake(
        a if a is not None else admission(),
        o if o is not None else observation(),
        at=at,
        ledger=ledger or OneEventLocalLedger(),
    )


def test_is_dormant_local_only_and_has_strict_ttl():
    assert OFFLINE_ONLY is True
    assert DEFAULT_ENABLED is False
    assert MAX_TTL == timedelta(minutes=5)


def test_single_fake_positive_boolean_only_no_identifier():
    result = evaluate()
    assert result["decision"] == "PASS_FAKE_LOCAL_ONLY"
    assert result["reason"] == "LOCAL_DESIGN_QUALIFIED_NOT_HOSTED"
    assert set(result["checks"]) == set(FLAGS)
    assert all(v is True for v in result["checks"].values())
    assert len(result["audit_receipt"]) == 24
    serialized = str(result)
    assert "910001" not in serialized
    assert CURRENT_SOURCE_PIN not in serialized
    assert "FAKE-M1-WND-TICKET" not in serialized


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": 2},
        {"tenant_id": 910002},
        {"tenant_id": True},
        {"synthetic_scope_preapproved": False},
        {"issuer_attested": False},
        {"schema_pin_attested": False},
        {"reader_acl_attested": False},
        {"source_pin": "0" * 40},
        {"runtime_pin": "f" * 40},
        {"event_ticket": "bad"},
        {"event_ticket": "FAKE-M1-WND-' OR 1=1"},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"issued_at": NOW + timedelta(seconds=10)},
        {"issued_at": NOW - timedelta(minutes=10)},
        {"expires_at": NOW + timedelta(minutes=10)},
        {"expires_at": NOW + timedelta(seconds=301)},
        {"issued_at": NOW.replace(tzinfo=None)},
        {"expires_at": NOW.replace(tzinfo=None)},
    ],
)
def test_attestation_envelope_fail_closed(changes):
    result = evaluate(admission(**changes))
    assert result["decision"] == "HOLD"
    assert result["checks"] == {}
    assert result["audit_receipt"] is None


@pytest.mark.parametrize("key", FLAGS)
def test_every_boolean_security_control_is_mandatory(key):
    assert evaluate(o=observation(**{key: False}))["decision"] == "HOLD"


@pytest.mark.parametrize("key", COUNTS)
@pytest.mark.parametrize("count", [0, 2, -1, 100, True, "1"])
def test_cardinality_must_be_exactly_one_not_bool(key, count):
    assert evaluate(o=observation(**{key: count}))["reason"] == "HOLD_CARDINALITY"


@pytest.mark.parametrize(
    "key",
    [
        "secret", "token", "secret_hash", "lookup_hash", "key_prefix",
        "digest", "database_url", "raw_merchant_id", "sql",
        "customer_phone", "payment_account", "tenant2_records",
        "user_selected_tenant", "user_sql_selector",
    ],
)
def test_secret_or_arbitrary_field_must_fail_without_echo(key):
    marker = "FAKE_NEVER_EXPOSE_123"
    result = evaluate(o=observation(**{key: marker}))
    assert result["reason"] == "HOLD_FIELDSET"
    assert marker not in str(result)
    assert key not in str(result)


def test_missing_field_denied():
    rows = observation()
    rows.pop("r5h_disabled")
    assert evaluate(o=rows)["reason"] == "HOLD_FIELDSET"


@pytest.mark.parametrize("wrong", [1, 0, "true", None, [], {"ok": True}])
def test_boolean_strictly_typed(wrong):
    assert evaluate(o=observation(reader_effective=wrong))["reason"] == "HOLD_FIELD_TYPE"


def test_nonce_single_use_even_with_exact_replay():
    ledger = OneEventLocalLedger()
    assert evaluate(ledger=ledger)["decision"] == "PASS_FAKE_LOCAL_ONLY"
    assert evaluate(ledger=ledger)["reason"] == "HOLD_REPLAY"


def test_fresh_distinct_fake_event_can_pass():
    ledger = OneEventLocalLedger()
    assert evaluate(ledger=ledger)["decision"] == "PASS_FAKE_LOCAL_ONLY"
    assert evaluate(admission(event_ticket="FAKE-M1-WND-TICKET-002"), ledger=ledger)["decision"] == "PASS_FAKE_LOCAL_ONLY"


def test_naive_time_never_accepted():
    assert evaluate(at=NOW.replace(tzinfo=None))["reason"] == "HOLD_TIME"


def test_wrong_types_fail_closed():
    assert evaluate_local_fake(None, observation(), at=NOW, ledger=OneEventLocalLedger())["decision"] == "HOLD"
    assert evaluate_local_fake(admission(), {"token": "fake"}, at=NOW, ledger=object())["decision"] == "HOLD"


def test_no_secret_or_sql_dependencies_imported():
    import inspect

    import scripts.msar_wnd_nosecret_evidence as module

    source = inspect.getsource(module)
    assert "import sqlalchemy" not in source
    assert "import psycopg" not in source
    assert "os.environ" not in source
    assert "engine.connect" not in source
    assert "httpx" not in source
    assert "requests." not in source
