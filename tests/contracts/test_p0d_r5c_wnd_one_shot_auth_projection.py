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


# R5F: only local, fake-role, catalog-only diagnostics. No hosted connection.
from types import SimpleNamespace

from sqlalchemy import create_engine


def _r5f_local_environment(**overrides):
    values = {
        r5c.R5F_LOCAL_ENABLE: "1",
        r5c.R5F_LOCAL_EXPIRES: (NOW + timedelta(minutes=5)).isoformat(),
    }
    values.update(overrides)
    return values


class R5FResult:
    def __init__(self, data):
        self.data = data

    def mappings(self):
        return self

    def one(self):
        return self.data


class R5FConnection:
    def __init__(self, changes=None, *, fail=False):
        self.row = {
            "session_identity_match": True, "role_exists": True,
            "is_super": False, "bypass_rls": False,
            "create_role": False, "create_db_role": False,
            "replicate": False, "inherits": True,
            "database_create": False, "schema_create": False,
            "direct_memberships": 0, "target_count": 13,
            "missing_count": 0, "owned_count": 0,
            "select_count": 0, "write_count": 0,
            "rls_count": 0, "force_rls_count": 0,
            "policy_count": 0, "owned_database_count": 0,
            "owned_schema_count": 0,
        }
        self.row.update(changes or {})
        self.fail = fail
        self.statements = []
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def begin(self):
        return self

    @property
    def is_active(self):
        return not self.rolled_back

    def rollback(self):
        self.rolled_back = True

    def execute(self, statement, *_args):
        sql = str(statement)
        self.statements.append(sql)
        if self.fail and "r5f:fixed-local" in sql:
            raise TimeoutError("private-secret-value-must-not-appear")
        return R5FResult(self.row)


class R5FEngine:
    def __init__(self, changes=None, *, fail=False, host="127.0.0.1",
                 port=55673, database="r5f_fixture_synthetic",
                 username="r5f_reader"):
        self.url = SimpleNamespace(
            drivername="postgresql+psycopg2", host=host, port=port,
            database=database, username=username,
        )
        self.connection = R5FConnection(changes, fail=fail)
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return self.connection


def _r5f_run(engine=None, **env_changes):
    engine = engine or R5FEngine()
    result = r5c.run_r5f_local_metadata(
        engine, environ=_r5f_local_environment(**env_changes), now=NOW,
    )
    return engine, result


def test_r5f_default_off_never_connects():
    engine = R5FEngine()
    result = r5c.run_r5f_local_metadata(engine, environ={}, now=NOW)
    assert result["gate"] == "DISABLED"
    assert engine.connect_calls == 0


@pytest.mark.parametrize("date", [
    (NOW - timedelta(seconds=1)).isoformat(),
    (NOW + timedelta(minutes=11)).isoformat(),
    "garbage",
])
def test_r5f_expiry_bad_never_connects(date):
    engine = R5FEngine()
    _, result = _r5f_run(
        engine, **{r5c.R5F_LOCAL_EXPIRES: date},
    )
    assert result["gate"] == "HOLD_EXPIRED"
    assert engine.connect_calls == 0


@pytest.mark.parametrize("key,value", [
    ("RENDER", "true"),
    ("RENDER_SERVICE_ID", "srv-db3vej67bikc73ai2080"),
    ("DATABASE_URL", "postgresql://hosted-secret"),
    ("PGHOST", "private.database.render.com"),
])
def test_r5f_rejects_hosted_marker_before_connect(key, value):
    engine, result = _r5f_run(R5FEngine(), **{key: value})
    assert result["gate"] == "HOLD_HOSTED_CONTEXT"
    assert engine.connect_calls == 0


@pytest.mark.parametrize("changes", [
    {"host": "localhost"},
    {"host": "internal.render.com"},
    {"port": 5432},
    {"port": 8001},
    {"database": "wnd_xafpay_demo_austin_db"},
    {"username": "wnd_xafpay_demo_austin_db_user"},
])
def test_r5f_rejects_untrusted_engine_before_connect(changes):
    engine, result = _r5f_run(R5FEngine(**changes))
    assert result["gate"] == "HOLD_NONLOCAL_ENGINE"
    assert engine.connect_calls == 0


def test_r5f_no_application_engine_or_startup_registration():
    import inspect

    assert r5c.run_r5f_local_metadata.__code__.co_argcount >= 1
    source = inspect.getsource(r5c.register_startup_diagnostic)
    assert "run_r5f_local_metadata" not in source
    assert "from database import engine" not in inspect.getsource(
        r5c.run_r5f_local_metadata,
    )


def test_r5f_catalog_sql_is_one_fixed_select_with_no_base_table_data_reads():
    sql = r5c._R5F_FIXED_CATALOG_SQL
    assert sql.count("/* r5f:fixed-local") == 1
    assert sql.count("SELECT") >= 1
    assert "FROM tenants" not in sql
    assert "FROM pa_merchants" not in sql
    assert "FROM service_identities" not in sql
    assert "FROM pg_catalog.pg_class" not in sql  # must schema-qualify?
    assert "FROM pg_catalog.pg_auth_members" in sql
    assert ":tenant" not in sql
    for unsafe in ("UPDATE ", "DELETE FROM", "INSERT INTO", "ALTER ", "DROP "):
        assert unsafe not in sql


def test_r5f_positive_catalog_is_not_tenant_proof():
    engine, result = _r5f_run()
    assert result["gate"] == "PASS"
    assert result["metadata"] == "PASS"
    assert result["reader"] == "PASS_CATALOG_ONLY_NO_BASE_SELECT"
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    assert result["target_count"] == 13
    assert engine.connection.rolled_back
    assert len(engine.connection.statements) == 5
    assert engine.connection.statements[0] == "SET TRANSACTION READ ONLY"


@pytest.mark.parametrize("change", [
    {"is_super": True}, {"bypass_rls": True}, {"create_role": True},
    {"create_db_role": True}, {"replicate": True},
    {"database_create": True}, {"schema_create": True},
    {"owned_count": 1}, {"owned_schema_count": 1},
    {"owned_database_count": 1}, {"write_count": 1},
    {"direct_memberships": 1}, {"session_identity_match": False},
])
def test_r5f_privilege_and_inheritance_negatives(change):
    _, result = _r5f_run(R5FEngine(change))
    assert result["reader"] == "HOLD_OVERBROAD_READER"
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"


@pytest.mark.parametrize("change,expected", [
    ({"select_count": 13}, "HOLD_BROAD_BASE_SELECT"),
    ({"missing_count": 1}, "HOLD_SCHEMA"),
    ({"target_count": 12}, "HOLD_UNPROVEN"),
    ({"target_count": 14}, "HOLD_UNPROVEN"),
    ({"policy_count": 999999}, "HOLD_UNPROVEN"),
    ({"direct_memberships": "private name"}, "HOLD_UNPROVEN"),
])
def test_r5f_schema_broad_reader_and_output_bounds(change, expected):
    _, result = _r5f_run(R5FEngine(change))
    assert result["reader"] == expected
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"


def test_r5f_timeout_fails_closed_no_raw_error_or_credentials():
    engine, result = _r5f_run(R5FEngine(fail=True))
    assert result["metadata"] == "HOLD_DATABASE_FAILURE"
    assert engine.connection.rolled_back
    assert "private-secret-value" not in json.dumps(result)


def test_r5f_probes_never_return_real_fake_row_values_or_raw_roles():
    engine, result = _r5f_run(R5FEngine())
    assert set(result).issubset({
        "generation", "gate", "metadata", "reader", "tenant_isolation",
        "target_count", "missing_count", "direct_memberships", "select_count",
        "write_count", "owned_count", "rls_count", "force_rls_count",
        "policy_count",
    })
    assert "secret" not in json.dumps(result)
    assert "tenant_id" not in json.dumps(result)
    assert engine.connection.rolled_back


def test_r5f_real_pg17_catalog_local_if_explicit_fixture(monkeypatch):
    """Only run with an operator-created disposable PG17 loopback fixture."""
    dsn = os.environ.get("R5F_FIXTURE_LOCAL_PG17_URL")
    if not dsn:
        pytest.skip("Disposable PG17 local fixture not configured")
    engine = create_engine(dsn, connect_args={"connect_timeout": 2})
    try:
        # The local-only gate checks URL host, user, port, and fixture DB prefix.
        _, result = _r5f_run(engine)
        assert result["gate"] == "PASS"
        assert result["metadata"] == "PASS"
        assert result["target_count"] == 13
        assert result["reader"] in {
            "PASS_CATALOG_ONLY_NO_BASE_SELECT",
            "HOLD_OVERBROAD_READER",
            "HOLD_BROAD_BASE_SELECT",
        }
        assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    finally:
        engine.dispose()



def test_r5f_pg17_real_unauthorized_tenant2_and_foreign_reads_denied():
    dsn = os.environ.get("R5F_FIXTURE_LOCAL_PG17_URL")
    if not dsn:
        pytest.skip("Disposable PG17 local fixture not configured")
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    engine = create_engine(dsn, connect_args={"connect_timeout": 2})
    try:
        assert r5c.r5f_local_gate(
            engine, environ=_r5f_local_environment(), now=NOW,
        ) == "PASS"
        for tenant in (2, 777777, 910001):
            with engine.connect() as conn, pytest.raises(DBAPIError):
                conn.execute(
                    text("SELECT fake_marker FROM public.tenants WHERE tenant_id=:t"),
                    {"t": tenant},
                ).all()
        with engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(
                text("INSERT INTO public.tenants(tenant_id,fake_marker) VALUES (2,'no')"),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("role,reader_state", [
    ("r5f_reader", "PASS_CATALOG_ONLY_NO_BASE_SELECT"),
    ("r5f_broad", "HOLD_BROAD_BASE_SELECT"),
    ("r5f_inherit", "HOLD_OVERBROAD_READER"),
    ("r5f_admin", "HOLD_OVERBROAD_READER"),
])
def test_r5f_pg17_real_fake_role_privileges_and_inheritance(role, reader_state):
    dsn = os.environ.get("R5F_FIXTURE_LOCAL_PG17_URL")
    if not dsn:
        pytest.skip("Disposable PG17 local fixture not configured")
    from sqlalchemy.engine import make_url

    url = make_url(dsn).set(username=role)
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        result = r5c.run_r5f_local_metadata(
            engine, environ=_r5f_local_environment(), now=NOW,
        )
        assert result["metadata"] == "PASS"
        assert result["reader"] == reader_state
        assert result["tenant_isolation"] == "HOLD_UNPROVEN"
        assert result["target_count"] == 13
        assert result["missing_count"] == 0
    finally:
        engine.dispose()


# PCR V17 R5H: separate default-off, hosted-specific source candidate tests.
R5H_ATTESTED_SHA = "c" * 40
R5H_FAKE_INSTANCE = r5c.EXPECTED_RENDER_SERVICE_ID + "-fake123"

def r5h_environment(**overrides):
    values = {
        r5c.R5H_ENABLE_ENV: "1",
        r5c.R5H_EXPIRES_ENV: (NOW + timedelta(minutes=5)).isoformat(),
        r5c.R5H_APPROVED_SHA_ENV: R5H_ATTESTED_SHA,
        r5c.R5H_EVENT_ENV: "abc123def4567890",
        r5c.R5H_INSTANCE_SERVICE_ENV: r5c.EXPECTED_RENDER_SERVICE_ID,
        "RENDER": "true",
        "RENDER_SERVICE_ID": r5c.EXPECTED_RENDER_SERVICE_ID,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": r5c.EXPECTED_RENDER_HOST,
        "RENDER_GIT_BRANCH": r5c.EXPECTED_RENDER_BRANCH,
        "RENDER_REGION": r5c.R5H_EXPECTED_REGION,
        "RENDER_GIT_COMMIT": R5H_ATTESTED_SHA,
        "HOSTNAME": R5H_FAKE_INSTANCE,
        r5c.ENABLE_ENV: "0",
    }
    values.update(overrides)
    return values


class R5HConnection(R5FConnection):
    def __init__(self, changes=None, *, fail_marker=None):
        super().__init__()
        self.row.update({
            "database_ok": True, "current_user_ok": True,
            "session_user_ok": True,
        })
        self.row.update(changes or {})
        self.fail_marker = fail_marker

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if self.fail_marker and self.fail_marker in sql:
            raise TimeoutError("private-hosted-password-must-not-leak")
        return R5FResult(self.row)


class R5HEngine(R5FEngine):
    def __init__(self, changes=None, *, fail_marker=None):
        super().__init__()
        self.connection = R5HConnection(changes, fail_marker=fail_marker)


def r5h_run(monkeypatch, engine=None, environment=None):
    monkeypatch.setattr(r5c, "_R5H_CLAIMED", False)
    engine = engine or R5HEngine()
    result = r5c.run_r5h_hosted_catalog(
        engine, environ=environment if environment is not None
        else r5h_environment(), now=NOW,
    )
    return engine, result


def test_r5h_default_disabled_never_connects(monkeypatch):
    engine, result = r5h_run(monkeypatch, environment={})
    assert result["gate"] == "DISABLED"
    assert engine.connect_calls == 0
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"


@pytest.mark.parametrize(("key", "invalid", "expected"), [
    (r5c.R5H_ENABLE_ENV, "unexpected", "HOLD_ENABLE_INVALID"),
    (r5c.R5H_EXPIRES_ENV, "not-a-date", "HOLD_EXPIRED_OR_OVERSCOPED"),
    (r5c.R5H_EXPIRES_ENV, (NOW - timedelta(seconds=1)).isoformat(), "HOLD_EXPIRED_OR_OVERSCOPED"),
    (r5c.R5H_EXPIRES_ENV, (NOW + timedelta(minutes=11)).isoformat(), "HOLD_EXPIRED_OR_OVERSCOPED"),
    ("RENDER", "false", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_SERVICE_ID", "another-service", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_SERVICE_TYPE", "worker", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_EXTERNAL_HOSTNAME", "foreign.render.com", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_GIT_BRANCH", "foreign-branch", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_REGION", "oregon", "HOLD_RUNTIME_ATTESTATION"),
    ("RENDER_GIT_COMMIT", "d"*40, "HOLD_SOURCE_ATTESTATION"),
    (r5c.R5H_APPROVED_SHA_ENV, "", "HOLD_SOURCE_ATTESTATION"),
    (r5c.R5H_EVENT_ENV, "invalid", "HOLD_RELEASE_EVENT"),
    ("HOSTNAME", "wrong-instance", "HOLD_INSTANCE_ATTESTATION"),
    (r5c.R5H_INSTANCE_SERVICE_ENV, "", "HOLD_INSTANCE_ATTESTATION"),
    (r5c.ENABLE_ENV, "1", "HOLD_R5C_CONFLICT"),
])
def test_r5h_context_negatives_stop_before_sql(monkeypatch, key, invalid, expected):
    engine, result = r5h_run(
        monkeypatch, environment=r5h_environment(**{key: invalid})
    )
    assert result["gate"] == expected
    assert engine.connect_calls == 0


def test_r5h_catalog_only_positive_mock_never_claims_tenant_isolation(monkeypatch):
    engine, result = r5h_run(monkeypatch)
    assert result["gate"] == "PASS"
    assert result["identity"] == "PASS"
    assert result["metadata"] == "PASS"
    assert result["reader"] == "PASS_CATALOG_ONLY_NO_BASE_SELECT"
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    assert len(engine.connection.statements) == 6
    assert engine.connection.statements[0] == "SET TRANSACTION READ ONLY"
    assert "r5h:identity" in engine.connection.statements[4]
    assert "r5f:fixed-local" in engine.connection.statements[5]
    assert engine.connection.rolled_back


@pytest.mark.parametrize("changes", [
    {"database_ok": False}, {"current_user_ok": False},
    {"session_user_ok": False}, {"session_user_ok": None},
])
def test_r5h_wrong_database_or_principal_never_executes_catalog(monkeypatch, changes):
    engine, result = r5h_run(monkeypatch, engine=R5HEngine(changes))
    assert result["identity"] == "HOLD_DB_IDENTITY"
    assert result["reader"] == "HOLD_UNPROVEN"
    assert len(engine.connection.statements) == 5
    assert engine.connection.rolled_back


@pytest.mark.parametrize("changes,expected", [
    ({"is_super": True}, "HOLD_OVERBROAD_READER"),
    ({"bypass_rls": True}, "HOLD_OVERBROAD_READER"),
    ({"create_role": True}, "HOLD_OVERBROAD_READER"),
    ({"create_db_role": True}, "HOLD_OVERBROAD_READER"),
    ({"database_create": True}, "HOLD_OVERBROAD_READER"),
    ({"schema_create": True}, "HOLD_OVERBROAD_READER"),
    ({"direct_memberships": 1}, "HOLD_OVERBROAD_READER"),
    ({"write_count": 1}, "HOLD_OVERBROAD_READER"),
    ({"owned_count": 1}, "HOLD_OVERBROAD_READER"),
    ({"owned_database_count": 1}, "HOLD_OVERBROAD_READER"),
    ({"select_count": 13}, "HOLD_BROAD_BASE_SELECT"),
    ({"missing_count": 1}, "HOLD_UNPROVEN"),
    ({"target_count": 1}, "HOLD_UNPROVEN"),
    ({"policy_count": 999999}, "HOLD_UNPROVEN"),
    ({"direct_memberships": "not-an-integer"}, "HOLD_UNPROVEN"),
])
def test_r5h_catalog_security_negatives(monkeypatch, changes, expected):
    engine, result = r5h_run(monkeypatch, engine=R5HEngine(changes))
    assert result["reader"] == expected
    assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    assert engine.connection.rolled_back


def test_r5h_replay_guard_no_second_connection(monkeypatch):
    monkeypatch.setattr(r5c, "_R5H_CLAIMED", False)
    engine = R5HEngine()
    first = r5c.run_r5h_hosted_catalog(
        engine, environ=r5h_environment(), now=NOW,
    )
    second = r5c.run_r5h_hosted_catalog(
        engine, environ=r5h_environment(), now=NOW,
    )
    assert first["identity"] == "PASS"
    assert second["gate"] == "HOLD_ALREADY_EXECUTED"
    assert engine.connect_calls == 1


@pytest.mark.parametrize("fail_marker", ["r5h:identity", "r5f:fixed-local"])
def test_r5h_timeout_sanitized_and_rollback(monkeypatch, fail_marker):
    engine, result = r5h_run(
        monkeypatch, engine=R5HEngine(fail_marker=fail_marker)
    )
    assert result["metadata"] == "HOLD_DATABASE_FAILURE"
    assert "private-hosted-password" not in json.dumps(result)
    assert engine.connection.rolled_back


def test_r5h_fixed_sql_cannot_access_tenant_rows():
    source = r5c._R5H_IDENTITY_SQL + r5c._R5F_FIXED_CATALOG_SQL
    assert "FROM public.tenants" not in source
    assert "FROM public.pa_merchants" not in source
    assert "FROM public.service_identities" not in source
    assert "FROM pg_catalog.pg_auth_members" in source
    assert "FROM pg_catalog.pg_roles" in source
    for forbidden in ("INSERT INTO", "UPDATE public.", "DELETE FROM public.",
                      "CREATE ROLE", "ALTER TABLE", "SELECT * FROM public."):
        assert forbidden not in source
    assert ":tenant" not in source
    assert ":table" not in source


def test_r5h_startup_hook_is_nonpublic_and_separate_from_r5c(monkeypatch):
    monkeypatch.delenv(r5c.R5H_ENABLE_ENV, raising=False)
    monkeypatch.delenv(r5c.ENABLE_ENV, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@127.0.0.1:9/r5h_no_db")
    monkeypatch.setenv("JWT_SECRET", "fake-unit-only")
    monkeypatch.setenv("GATEWAY_API_KEY", "fake-unit-only")
    from startup import create_app
    app = create_app()
    handlers = [getattr(f, "__name__", "") for f in app.router.on_startup]
    assert "run_startup_diagnostic" in handlers
    assert "run_r5h_hosted_startup_diagnostic" in handlers
    assert not any(
        "r5h" in getattr(route, "path", "").lower()
        for route in app.routes
    )


def test_r5h_disabled_startup_never_imports_application_engine(monkeypatch):
    monkeypatch.delenv(r5c.R5H_ENABLE_ENV, raising=False)
    emitted = []
    monkeypatch.setattr(r5c._R5H_LOGGER, "warning", lambda *args: emitted.append(args))
    r5c.run_r5h_hosted_startup_diagnostic()
    assert emitted == []


def test_r5h_rejects_current_app_principal_broad_mock(monkeypatch):
    _, result = r5h_run(
        monkeypatch,
        engine=R5HEngine({"write_count": 13, "owned_count": 12}),
    )
    assert result["reader"] == "HOLD_OVERBROAD_READER"


def test_r5h_pg17_disposable_catalog_and_wrong_principal(monkeypatch):
    dsn = os.environ.get("R5F_FIXTURE_LOCAL_PG17_URL")
    if not dsn:
        pytest.skip("No disposable fake PG17; never connect to hosted WND")
    from sqlalchemy.engine import make_url

    # Explicit local fake-only URL; this is NOT a hosted admission grant.
    url = make_url(dsn)
    assert url.host == "127.0.0.1"
    assert url.database.startswith("r5f_fixture_")
    assert url.username == "r5f_reader"
    assert url.port not in (None, 5432)
    assert url.password is None
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        monkeypatch.setattr(r5c, "_R5H_CLAIMED", False)
        # The fake reader must fail the exact WND principal identity attestation.
        result = r5c.run_r5h_hosted_catalog(
            engine, environ=r5h_environment(), now=NOW
        )
        assert result["identity"] == "HOLD_DB_IDENTITY"
        assert result["reader"] == "HOLD_UNPROVEN"
        assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    finally:
        engine.dispose()



def test_r5h_pg17_disposable_positive_fixed_catalog_after_fake_attestation(monkeypatch):
    """Local fake-only attestation: prove real PG17 SQL without hosted WND."""
    dsn = os.environ.get("R5F_FIXTURE_LOCAL_PG17_URL")
    if not dsn:
        pytest.skip("No disposable PG17 fake fixture")
    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    assert url.host == "127.0.0.1"
    assert url.port not in (None, 5432)
    assert url.database.startswith("r5f_fixture_")
    assert url.username == "r5f_reader"
    assert url.password is None
    # These monkeypatches intentionally exist ONLY in a disposable local
    # test process; production constant values are never modified on disk.
    monkeypatch.setattr(r5c, "EXPECTED_DATABASE", url.database)
    monkeypatch.setattr(r5c, "EXPECTED_DATABASE_USER", url.username)
    monkeypatch.setattr(r5c, "_R5H_CLAIMED", False)
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        result = r5c.run_r5h_hosted_catalog(
            engine, environ=r5h_environment(), now=NOW
        )
        assert result["gate"] == "PASS"
        assert result["identity"] == "PASS"
        assert result["metadata"] == "PASS"
        assert result["reader"] == "PASS_CATALOG_ONLY_NO_BASE_SELECT"
        assert result["target_count"] == 13
        assert result["tenant_isolation"] == "HOLD_UNPROVEN"
    finally:
        engine.dispose()
