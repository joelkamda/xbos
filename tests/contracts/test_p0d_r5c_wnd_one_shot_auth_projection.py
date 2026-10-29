from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from scripts import p0d_r5c_wnd_one_shot_auth_projection as r5c

NOW = datetime(2026, 10, 29, 9, 30, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, *, mapping=None, scalar=None):
        self._mapping = mapping
        self._scalar = scalar

    def mappings(self):
        return self

    def one(self):
        if self._mapping is None:
            raise AssertionError("mapping result not configured")
        return self._mapping

    def scalar_one(self):
        if self._scalar is None:
            raise AssertionError("scalar result not configured")
        return self._scalar


class FakeTransaction:
    def __init__(self):
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


class FakeConnection:
    def __init__(self, scenario=None):
        self.scenario = dict(scenario or {})
        self.statements = []
        self.params = []
        self.transaction = FakeTransaction()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def begin(self):
        return self.transaction

    def execute(self, statement, params=None):
        sql = str(statement)
        params = dict(params or {})
        self.statements.append(sql)
        self.params.append(params)

        fail_marker = self.scenario.get("fail_marker")
        if fail_marker and fail_marker in sql:
            raise TimeoutError("synthetic timeout with secret=must-not-leak")

        if sql.lstrip().startswith("SET "):
            return FakeResult(scalar=1)

        if "r5c:identity" in sql:
            identity = {
                "database_ok": True,
                "current_user_ok": True,
                "session_user_ok": True,
                "rolsuper": False,
                "rolbypassrls": False,
                "rolcreaterole": False,
                "rolcreatedb": False,
                "rolreplication": False,
                "database_create": False,
                "schema_create": False,
            }
            identity.update(self.scenario.get("identity", {}))
            return FakeResult(mapping=identity)

        if "r5c:table-metadata" in sql:
            value = {
                "exists_ok": True,
                "select_ok": True,
                "write_effective": False,
                "owned_by_current_user": False,
            }
            value.update(self.scenario.get("tables", {}).get(params["table_name"], {}))
            return FakeResult(mapping=value)

        if "r5c:tenant" in sql:
            return FakeResult(scalar=self.scenario.get("tenant_count", 1))
        if "r5c:merchant" in sql:
            return FakeResult(scalar=self.scenario.get("merchant_count", 1))
        if "r5c:structure" in sql:
            value = {
                "mapping_count": 1,
                "branch_count": 1,
                "location_count": 1,
                "organization_count": 1,
            }
            value.update(self.scenario.get("structure", {}))
            return FakeResult(mapping=value)
        if "r5c:service-identity" in sql:
            return FakeResult(scalar=self.scenario.get("service_count", 1))
        if "r5c:service-assignment" in sql:
            value = {"assignment_count": 1, "location_count": 1, "identity_count": 1}
            value.update(self.scenario.get("assignment", {}))
            return FakeResult(mapping=value)
        if "r5c:checkout-permission" in sql:
            value = {"path_count": 1, "location_count": 1, "identity_count": 1}
            value.update(self.scenario.get("permission", {}))
            return FakeResult(mapping=value)
        if "r5c:checkout-context" in sql:
            return FakeResult(scalar=self.scenario.get("context_count", 1))
        if "r5c:catalog" in sql:
            value = {
                "binding_count": 1,
                "merchant_count": 1,
                "location_count": 1,
                "active_mode_count": 1,
            }
            value.update(self.scenario.get("catalog", {}))
            return FakeResult(mapping=value)

        raise AssertionError(f"unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, scenario=None):
        self.connection = FakeConnection(scenario)

    def connect(self):
        return self.connection


def enabled_env(**overrides):
    value = {
        r5c.ENABLE_ENV: "1",
        r5c.EXPIRES_ENV: (NOW + timedelta(minutes=5)).isoformat(),
        "RENDER": "true",
        "RENDER_SERVICE_ID": r5c.EXPECTED_RENDER_SERVICE_ID,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": r5c.EXPECTED_RENDER_HOST,
        "RENDER_GIT_BRANCH": r5c.EXPECTED_RENDER_BRANCH,
    }
    value.update(overrides)
    return value


def test_default_off_short_circuits_before_database():
    emitted = []
    result = r5c.run_startup_diagnostic(
        environ={},
        now=NOW,
        engine=object(),
        emit=emitted.append,
        enforce_once=False,
    )
    assert result["gate"] == "DISABLED"
    assert result["reader"] == "NOT_RUN"
    assert emitted == [result]


@pytest.mark.parametrize("flag", ["yes", "true", "2", "forged"])
def test_forged_enable_flag_fails_closed(flag):
    result = r5c.run_startup_diagnostic(
        environ=enabled_env(**{r5c.ENABLE_ENV: flag}),
        now=NOW,
        engine=object(),
        emit=lambda _value: None,
        enforce_once=False,
    )
    assert result["gate"] == "HOLD_FLAG_INVALID"


@pytest.mark.parametrize(
    "expiry",
    [
        (NOW - timedelta(seconds=1)).isoformat(),
        (NOW + timedelta(minutes=11)).isoformat(),
        "not-a-date",
        "",
    ],
)
def test_expired_or_overscoped_gate_fails_closed(expiry):
    result = r5c.run_startup_diagnostic(
        environ=enabled_env(**{r5c.EXPIRES_ENV: expiry}),
        now=NOW,
        engine=object(),
        emit=lambda _value: None,
        enforce_once=False,
    )
    assert result["gate"] == "HOLD_GATE_EXPIRED_OR_OVERSCOPED"


@pytest.mark.parametrize(
    "change",
    [
        {"RENDER": "false"},
        {"RENDER_SERVICE_ID": "srv-other"},
        {"RENDER_SERVICE_TYPE": "worker"},
        {"RENDER_EXTERNAL_HOSTNAME": "other.onrender.com"},
        {"RENDER_GIT_BRANCH": "other"},
    ],
)
def test_wrong_runtime_context_never_opens_database(change):
    env = enabled_env(**change)
    result = r5c.run_startup_diagnostic(
        environ=env,
        now=NOW,
        engine=object(),
        emit=lambda _value: None,
        enforce_once=False,
    )
    assert result["gate"] == "HOLD_RUNTIME_CONTEXT"
    assert result["reader"] == "NOT_RUN"


def test_wrong_tenant_two_is_refused_before_sql():
    connection = FakeConnection()
    with pytest.raises(r5c.ProjectionHold, match="HOLD_TENANT_REFUSED"):
        r5c._stage_two(connection, tenant_id=2, at=NOW)
    assert connection.statements == []


def test_wrong_database_identity_stops_before_protected_projection():
    engine = FakeEngine({"identity": {"database_ok": False}})
    result = r5c.run_projection(engine, at=NOW)
    assert result["reader"] == "HOLD_DB_IDENTITY"
    assert result["schema"] == "HOLD_UNPROVEN"
    assert not any("r5c:tenant" in sql for sql in engine.connection.statements)


def test_schema_drift_stops_before_protected_projection():
    engine = FakeEngine({"tables": {"service_identities": {"exists_ok": False}}})
    result = r5c.run_projection(engine, at=NOW)
    assert result["schema"] == "HOLD_SCHEMA_DRIFT"
    assert result["reader"] == "HOLD_UNPROVEN"
    assert not any("r5c:tenant" in sql for sql in engine.connection.statements)


def test_missing_select_stops_before_protected_projection():
    engine = FakeEngine({"tables": {"permission_definitions": {"select_ok": False}}})
    result = r5c.run_projection(engine, at=NOW)
    assert result["schema"] == "PASS"
    assert result["reader"] == "HOLD_SELECT_DENIED"
    assert not any("r5c:tenant" in sql for sql in engine.connection.statements)


@pytest.mark.parametrize(
    "identity_change",
    [
        {"rolsuper": True},
        {"rolbypassrls": True},
        {"rolcreaterole": True},
        {"rolcreatedb": True},
        {"database_create": True},
        {"schema_create": True},
    ],
)
def test_overbroad_role_stops_before_protected_projection(identity_change):
    engine = FakeEngine({"identity": identity_change})
    result = r5c.run_projection(engine, at=NOW)
    assert result["reader"] == "HOLD_OVERBROAD_READER"
    assert not any("r5c:tenant" in sql for sql in engine.connection.statements)


@pytest.mark.parametrize(
    "table_change",
    [{"write_effective": True}, {"owned_by_current_user": True}],
)
def test_overbroad_table_rights_stop_before_protected_projection(table_change):
    engine = FakeEngine({"tables": {"tenants": table_change}})
    result = r5c.run_projection(engine, at=NOW)
    assert result["reader"] == "HOLD_OVERBROAD_READER"
    assert not any("r5c:tenant" in sql for sql in engine.connection.statements)


def test_admitted_reader_runs_only_fixed_synthetic_projection_and_no_writes():
    engine = FakeEngine()
    result = r5c.run_projection(engine, at=NOW)
    assert result == {
        "generation": r5c.GENERATION,
        "gate": "PASS",
        "reader": "PASS",
        "schema": "PASS",
        "tenant": "PASS",
        "merchant": "PASS",
        "structure": "PASS",
        "service_identity": "PASS",
        "service_assignment": "PASS",
        "checkout_permission": "PASS",
        "checkout_context": "PASS",
        "catalog": "PASS",
    }

    for sql in engine.connection.statements:
        normalized = sql.strip().upper()
        assert normalized.startswith(("SELECT", "/*", "SET"))
        assert not any(
            token in normalized
            for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE ", "ALTER ", "CREATE ", "DROP ")
        )
    for params in engine.connection.params:
        if "tenant" in params:
            assert params["tenant"] == r5c.TENANT_ID
            assert params["tenant"] != 2


def test_ambiguous_merchant_is_reported_without_raw_rows():
    result = r5c.run_projection(FakeEngine({"merchant_count": 2}), at=NOW)
    assert result["merchant"] == "AMBIGUOUS"


def test_ambiguous_service_identity_is_reported():
    result = r5c.run_projection(FakeEngine({"service_count": 2}), at=NOW)
    assert result["service_identity"] == "AMBIGUOUS"


def test_ambiguous_service_location_assignment_is_reported():
    result = r5c.run_projection(
        FakeEngine({"assignment": {"assignment_count": 2, "location_count": 2}}),
        at=NOW,
    )
    assert result["service_assignment"] == "AMBIGUOUS"


def test_disabled_permission_is_absent():
    result = r5c.run_projection(FakeEngine({"permission": {"path_count": 0}}), at=NOW)
    assert result["checkout_permission"] == "ABSENT"


def test_expired_or_ended_context_is_absent_after_source_predicates_filter_it():
    result = r5c.run_projection(FakeEngine({"context_count": 0}), at=NOW)
    assert result["checkout_context"] == "ABSENT"


def test_database_timeout_is_safe_hold_and_transaction_is_cleaned_up():
    engine = FakeEngine({"fail_marker": "r5c:identity"})
    result = r5c.run_projection(engine, at=NOW)
    assert result["reader"] == "HOLD_DATABASE_FAILURE"
    assert result["schema"] == "HOLD_UNPROVEN"
    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.closed is True


def test_connect_timeout_environment_is_restored(monkeypatch):
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "17")
    r5c.run_projection(FakeEngine(), at=NOW)
    assert os.environ["PGCONNECT_TIMEOUT"] == "17"


def test_safe_startup_output_never_contains_environment_secrets():
    emitted = []
    env = enabled_env(
        DATABASE_URL="postgresql://user:super-secret@example/db",
        XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN="another-secret",
    )
    result = r5c.run_startup_diagnostic(
        environ=env,
        now=NOW,
        engine=FakeEngine({"identity": {"database_create": True}}),
        emit=emitted.append,
        enforce_once=False,
    )
    payload = json.dumps(emitted)
    assert "super-secret" not in payload
    assert "another-secret" not in payload
    assert result["reader"] == "HOLD_OVERBROAD_READER"


def test_startup_returns_hold_instead_of_raising_on_database_failure():
    result = r5c.run_startup_diagnostic(
        environ=enabled_env(),
        now=NOW,
        engine=FakeEngine({"fail_marker": "r5c:identity"}),
        emit=lambda _value: None,
        enforce_once=False,
    )
    assert result["gate"] == "PASS"
    assert result["reader"] == "HOLD_DATABASE_FAILURE"


def test_once_per_process_claim_blocks_replay(monkeypatch):
    monkeypatch.setattr(r5c, "_ONCE_CLAIMED", False)
    first = r5c.run_startup_diagnostic(
        environ=enabled_env(),
        now=NOW,
        engine=FakeEngine(),
        emit=lambda _value: None,
        enforce_once=True,
    )
    second = r5c.run_startup_diagnostic(
        environ=enabled_env(),
        now=NOW,
        engine=FakeEngine(),
        emit=lambda _value: None,
        enforce_once=True,
    )
    assert first["reader"] == "PASS"
    assert second["gate"] == "HOLD_ALREADY_EXECUTED"


def test_application_has_no_r5c_http_route(monkeypatch):
    monkeypatch.delenv(r5c.ENABLE_ENV, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://import_only:import_only@127.0.0.1:9/r5c_import_only",
    )
    monkeypatch.setenv("JWT_SECRET", "r5c-import-only-not-a-real-secret")
    monkeypatch.setenv("GATEWAY_API_KEY", "r5c-import-only-not-a-real-key")
    from startup import create_app

    app = create_app()
    paths = tuple(getattr(route, "path", "") for route in app.routes)
    assert not any("r5c" in path.lower() for path in paths)
    assert not any("diagnostic" in path.lower() for path in paths)
