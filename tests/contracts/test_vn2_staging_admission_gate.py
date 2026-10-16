"""Synthetic-only VN2 staging safety tests; never connect to Render."""
import asyncio
import importlib
import sys
import types

import pytest

import vn2_staging_predeploy as pd
import vn2_staging_main as guard


def valid_env():
    host = pd.DB_RESOURCE_ID
    return {"XBOS_VN2_STAGING_PROFILE": "enabled",
            "XBOS_VN2_EXPECTED_PRIVATE_DB_HOST": host,
            "XBOS_VN2_EXPECTED_DATABASE_ID": pd.DB_RESOURCE_ID,
            "DATABASE_URL": f"postgresql://synthetic:fakepass@{host}:5432/{pd.DB_NAME}",
            "JWT_SECRET": "synthetic-test-only",
            "JWT_ALGORITHM": "HS256",
            "XBOS_BROWSER_ALLOWED_ORIGINS":
                "https://xafpay-xbos-neutral-vn2-staging.netlify.app"}


@pytest.mark.parametrize("mutations", [
    {"DATABASE_URL": None},
    {"XBOS_VN2_STAGING_PROFILE": None},
    {"XBOS_VN2_EXPECTED_DATABASE_ID": "dpg-wrong"},
    {"XBOS_VN2_EXPECTED_PRIVATE_DB_HOST": "other.internal"},
    {"DATABASE_URL": "postgresql://synthetic:fakepass@public.example:5432/" + pd.DB_NAME},
    {"DATABASE_URL": "postgresql://synthetic:fakepass@" + pd.DB_RESOURCE_ID + ":5432/other"},
    {"DATABASE_URL": "postgresql://synthetic:fakepass@" + pd.DB_RESOURCE_ID + ":5433/" + pd.DB_NAME},
    {"DATABASE_URL": "sqlite:///tmp/database"},
    {"DATABASE_URL": "postgresql://synthetic:fakepass@" + pd.DB_RESOURCE_ID
     + ":5432/" + pd.DB_NAME + "?sslmode=disable"},
])
def test_database_target_denial(mutations):
    env = valid_env()
    env.update(mutations)
    with pytest.raises(pd.AdmissionDenied):
        pd.target_url(env)


def test_valid_synthetic_target_and_config():
    env = valid_env()
    assert pd.target_url(env) == env["DATABASE_URL"]
    pd.security_config(env)


@pytest.mark.parametrize("changes", [
    {"JWT_SECRET": None},
    {"JWT_ALGORITHM": None},
    {"XBOS_BROWSER_ALLOWED_ORIGINS": None},
    {"XBOS_BROWSER_ALLOWED_ORIGINS": "https://other.example"},
])
def test_security_config_denial(changes):
    env = valid_env()
    env.update(changes)
    with pytest.raises(pd.AdmissionDenied):
        pd.security_config(env)


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return iter(self.value)


class FakeConnection:
    def __init__(self, **changes):
        self.state = dict(version=170005, database=pd.DB_NAME,
                          tables={"alembic_version", "xbos_browser_sessions"} | pd.DEPENDENCIES,
                          revision=[pd.REVISION], columns=pd.COLUMNS,
                          indexes=pd.INDEXES | {"xbos_browser_sessions_pkey"},
                          public_objects=0, other_clients=0)
        self.state.update(changes)
        self.sql = []

    def execute(self, statement):
        sql = str(statement)
        self.sql.append(sql)
        if "server_version_num" in sql:
            return Result(self.state["version"])
        if "current_database()" in sql and "pg_stat_activity" not in sql:
            return Result(self.state["database"])
        if "tablename FROM" in sql:
            return Result(self.state["tables"])
        if "FROM public.alembic_version" in sql:
            return Result(self.state["revision"])
        if "column_name FROM" in sql:
            return Result(self.state["columns"])
        if "indexname FROM" in sql:
            return Result(self.state["indexes"])
        if "pg_catalog.pg_class" in sql:
            return Result(self.state["public_objects"])
        if "pg_catalog.pg_stat_activity" in sql:
            return Result(self.state["other_clients"])
        if sql == "SET TRANSACTION READ ONLY":
            return Result(None)
        raise AssertionError("Unexpected SQL shape")


@pytest.mark.parametrize("changes", [
    {"version": 160005},
    {"database": "wrong"},
    {"tables": pd.DEPENDENCIES},
    {"revision": ["another_revision"]},
    {"tables": {"alembic_version", "xbos_browser_sessions"}},
    {"columns": pd.COLUMNS - {"last_rotated_at"}},
    {"indexes": {"xbos_browser_sessions_pkey"}},
])
def test_unready_schema_denied(changes):
    with pytest.raises(pd.AdmissionDenied):
        pd.check_schema(FakeConnection(**changes))


def test_exact_synthetic_ready_schema():
    conn = FakeConnection()
    pd.check_schema(conn)
    assert all("CREATE " not in sql and "INSERT " not in sql for sql in conn.sql)


@pytest.mark.parametrize("changes", [
    {"tables": {"unexpected"}},
    {"public_objects": 1},
    {"other_clients": 1},
])
def test_migration_prestate_rejects_existing_objects_or_sessions(changes):
    conn = FakeConnection(tables=set(), **changes) if "tables" not in changes else FakeConnection(**changes)
    with pytest.raises(pd.AdmissionDenied):
        pd.check_schema(conn, ready=False)


def test_empty_prestate_passes():
    pd.check_schema(FakeConnection(tables=set()), ready=False)


def test_database_readback_is_read_only(monkeypatch):
    conn = FakeConnection()
    class Engine:
        def connect(self):
            class Context:
                def __enter__(self):
                    return conn
                def __exit__(self, *args):
                    return False
            return Context()
        def dispose(self):
            pass
    monkeypatch.setattr(pd, "create_engine", lambda *_a, **_kw: Engine())
    monkeypatch.setattr(pd, "require_private_route", lambda url: None)
    pd.check_database("synthetic://never-connected")
    assert conn.sql[0] == "SET TRANSACTION READ ONLY"


def test_migration_failure_propagated_once(monkeypatch):
    calls = []
    monkeypatch.setattr(pd, "target_url", lambda: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda: None)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: calls.append(("readback", ready)))
    def fail(args, **kwargs):
        calls.append(("alembic", tuple(args)))
        return types.SimpleNamespace(returncode=42)
    monkeypatch.setattr(pd.subprocess, "run", fail)
    with pytest.raises(pd.AdmissionDenied, match="VN2_ALEMBIC_FAILED"):
        pd.predeploy()
    assert [x[0] for x in calls] == ["readback", "alembic"]
    assert calls[1][1][-2:] == ("upgrade", pd.REVISION)


def test_migration_success_readback(monkeypatch):
    sequence = []
    monkeypatch.setattr(pd, "target_url", lambda: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda: None)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: sequence.append(("check", ready)))
    def succeed(args, **kwargs):
        sequence.append(("upgrade", tuple(args)))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(pd.subprocess, "run", succeed)
    pd.predeploy()
    assert [x[0] for x in sequence] == ["check", "upgrade", "check"]
    assert sequence[0][1] is False and sequence[-1][1] is True


def asgi_call(scope):
    output = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        output.append(message)
    asyncio.run(guard.app(scope, receive, send))
    return output


@pytest.mark.parametrize("path", [
    "/health", "/kernel/browser-session/v1/login",
    "/kernel/auth/me", "/kernel/platform/v1/pack-template-discovery",
])
def test_unready_routes_denied_even_without_lifespan(monkeypatch, path):
    monkeypatch.setattr(guard, "security_config",
                        lambda: (_ for _ in ()).throw(pd.AdmissionDenied("synthetic")))
    monkeypatch.setattr(guard, "_delegate", None)
    response = asgi_call({"type": "http", "path": path, "method": "POST"})
    assert response[0]["status"] == 503
    assert not any(k == b"set-cookie" for k, _ in response[0]["headers"])
    assert guard._delegate is None


def test_database_unreachable_denies_even_after_delegate_cached(monkeypatch):
    async def fake(*args):
        raise AssertionError("Unready request reached application")
    monkeypatch.setattr(guard, "_delegate", fake)
    monkeypatch.setattr(guard, "security_config", lambda: None)
    monkeypatch.setattr(guard, "target_url", lambda: "synthetic")
    def failed(*a, **kw):
        raise ConnectionError("offline")
    monkeypatch.setattr(guard, "check_database", failed)
    assert asgi_call({"type": "http", "path": "/health"})[0]["status"] == 503


def test_unready_websocket_rejected(monkeypatch):
    monkeypatch.setattr(guard, "security_config",
                        lambda: (_ for _ in ()).throw(pd.AdmissionDenied("synthetic")))
    result = asgi_call({"type": "websocket", "path": "/kernel/browser-session/v1/login"})
    assert result == [{"type": "websocket.close", "code": 1008}]


def test_ready_state_delegates_without_changing_original_app(monkeypatch):
    called = []
    async def fake(scope, receive, send):
        called.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ready"})
    monkeypatch.setattr(guard, "_delegate", fake)
    monkeypatch.setattr(guard, "security_config", lambda: None)
    monkeypatch.setattr(guard, "target_url", lambda: "synthetic")
    monkeypatch.setattr(guard, "check_database", lambda *a, **kw: None)
    result = asgi_call({"type": "http", "path": "/health"})
    assert result[0]["status"] == 200
    assert called == ["/health"]


def test_import_does_not_open_database_or_import_generic_app():
    assert "from main import app" not in open(pd.__file__, encoding="utf-8").read()
    assert "from main import app" not in guard.app.__code__.co_names


@pytest.mark.parametrize("resolved", [
    ["8.8.8.8"], ["127.0.0.1"], ["192.0.2.5"],
    ["10.4.5.6", "8.8.8.8"], [],
])
def test_nonprivate_dns_rejected(monkeypatch, resolved):
    def answer(*args, **kwargs):
        return [(None, None, None, None, (ip, 5432)) for ip in resolved]
    monkeypatch.setattr(pd.socket, "getaddrinfo", answer)
    with pytest.raises(pd.AdmissionDenied):
        pd.require_private_route("postgresql://fake:fake@internal.example:5432/"
                                 + pd.DB_NAME)


def test_private_dns_accepted(monkeypatch):
    monkeypatch.setattr(pd.socket, "getaddrinfo",
                        lambda *a, **kw: [(None, None, None, None, ("10.0.10.8", 5432))])
    pd.require_private_route("postgresql://fake:fake@internal.example:5432/"
                             + pd.DB_NAME)


def test_private_dns_resolution_failure_denied(monkeypatch):
    def failed(*a, **kw):
        raise OSError("synthetic-unresolvable")
    monkeypatch.setattr(pd.socket, "getaddrinfo", failed)
    with pytest.raises(pd.AdmissionDenied):
        pd.require_private_route("postgresql://fake:fake@internal.example:5432/"
                                 + pd.DB_NAME)
