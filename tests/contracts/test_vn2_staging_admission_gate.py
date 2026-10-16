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
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: None)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: calls.append(("readback", ready)))
    def fail(args, **kwargs):
        calls.append(("alembic", tuple(args)))
        return types.SimpleNamespace(returncode=42)
    monkeypatch.setattr(pd.subprocess, "run", fail)
    with pytest.raises(pd.AdmissionDenied, match="VN2_ALEMBIC_FAILED"):
        pd.predeploy({"XBOS_VN2_PREDEPLOY_MODE": "bootstrap",
                      "XBOS_VN2_BOOTSTRAP_AUTHORIZED": "true"})
    assert [x[0] for x in calls] == ["readback", "alembic"]
    assert calls[1][1][-2:] == ("upgrade", pd.REVISION)


def test_migration_success_readback(monkeypatch):
    sequence = []
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: None)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: sequence.append(("check", ready)))
    def succeed(args, **kwargs):
        sequence.append(("upgrade", tuple(args)))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(pd.subprocess, "run", succeed)
    pd.predeploy({"XBOS_VN2_PREDEPLOY_MODE": "bootstrap",
                  "XBOS_VN2_BOOTSTRAP_AUTHORIZED": "true"})
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
    monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", "true")
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
    monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", "true")
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


@pytest.mark.parametrize("explicit", [False, True])
def test_provider_postgres_5432_port_variants(explicit):
    env = valid_env()
    port = ":5432" if explicit else ""
    env["DATABASE_URL"] = (
        f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}"
        f"{port}/{pd.DB_NAME}"
    )
    assert pd.target_url(env) == env["DATABASE_URL"]


@pytest.mark.parametrize("port", [":5433", ":5431", ":6543", ":0"])
def test_unapproved_postgres_port_rejected(port):
    env = valid_env()
    env["DATABASE_URL"] = (
        f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}"
        f"{port}/{pd.DB_NAME}"
    )
    with pytest.raises(pd.AdmissionDenied):
        pd.target_url(env)


@pytest.mark.parametrize("url", [
    "postgresql://synthetic:fakepass@public.example/xafpay_xbos_neutral_vn2_staging",
    "postgresql://synthetic:fakepass@dpg-wrong/xafpay_xbos_neutral_vn2_staging",
    f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}/wrong_database",
    f"postgresql://synthetic@{pd.PROVIDER_PRIVATE_HOST}/{pd.DB_NAME}",
    f"postgresql://:fakepass@{pd.PROVIDER_PRIVATE_HOST}/{pd.DB_NAME}",
    f"mysql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}/{pd.DB_NAME}",
    f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}/{pd.DB_NAME}?sslmode=disable",
    f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}/{pd.DB_NAME}#fragment",
])
def test_strict_database_url_rejects_invalid_components(url):
    env = valid_env()
    env["DATABASE_URL"] = url
    with pytest.raises(pd.AdmissionDenied):
        pd.target_url(env)


def test_provider_host_expected_metadata_is_not_arbitrary():
    env = valid_env()
    env["XBOS_VN2_EXPECTED_PRIVATE_DB_HOST"] = "other.internal"
    env["DATABASE_URL"] = (
        f"postgresql://synthetic:fakepass@other.internal/{pd.DB_NAME}"
    )
    with pytest.raises(pd.AdmissionDenied, match="VN2_PRIVATE_HOST_UNVERIFIED"):
        pd.target_url(env)


@pytest.mark.parametrize("explicit", [False, True])
def test_private_dns_resolves_effective_5432(monkeypatch, explicit):
    requests = []
    def fake_dns(host, port, **kwargs):
        requests.append((host, port))
        return [(None, None, None, None, ("10.2.3.4", port))]
    monkeypatch.setattr(pd.socket, "getaddrinfo", fake_dns)
    port = ":5432" if explicit else ""
    pd.require_private_route(
        f"postgresql://synthetic:fakepass@{pd.PROVIDER_PRIVATE_HOST}{port}/{pd.DB_NAME}"
    )
    assert requests == [(pd.PROVIDER_PRIVATE_HOST, 5432)]


def test_verify_only_ready_schema_without_alembic(monkeypatch):
    order = []
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: order.append("secrets"))
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: order.append(("read_only", ready)))
    monkeypatch.setattr(pd.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("verify-only attempted alembic")))
    pd.predeploy({})
    assert order == ["secrets", ("read_only", True)]


@pytest.mark.parametrize("unready", [
    FakeConnection(tables=set()),
    FakeConnection(tables={"alembic_version", "xbos_browser_sessions"},
                   revision=["incomplete_revision"]),
    FakeConnection(tables={"other_table"}),
])
def test_verify_only_rejects_empty_partial_unknown_schema(monkeypatch, unready):
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: None)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: pd.check_schema(unready, ready))
    monkeypatch.setattr(pd.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("alembic attempted")))
    with pytest.raises(pd.AdmissionDenied):
        pd.predeploy({})


@pytest.mark.parametrize("mode,approval", [
    ("bootstrap", None), ("bootstrap", ""), ("bootstrap", "false"),
    ("bootstrap", "True"), ("bootstrap", "1"),
    ("other", "true"), ("", "true"),
])
def test_bootstrap_requires_explicit_separate_gate(monkeypatch, mode, approval):
    monkeypatch.setattr(pd, "target_url", lambda env=None: (_ for _ in ()).throw(
        AssertionError("Unadmitted mode reached database configuration")))
    env = {"XBOS_VN2_PREDEPLOY_MODE": mode}
    if approval is not None:
        env["XBOS_VN2_BOOTSTRAP_AUTHORIZED"] = approval
    with pytest.raises(pd.AdmissionDenied):
        pd.predeploy(env)


def test_bootstrap_cannot_repeat_after_first_migration(monkeypatch):
    state = {"migrated": False, "upgrades": 0}
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: None)
    def check(url, ready=True):
        if ready:
            assert state["migrated"]
        elif state["migrated"]:
            raise pd.AdmissionDenied("VN2_PRESTATE_NONEMPTY_OR_ACTIVE")
    monkeypatch.setattr(pd, "check_database", check)
    def upgrade(*args, **kwargs):
        state["upgrades"] += 1
        state["migrated"] = True
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(pd.subprocess, "run", upgrade)
    bootstrap = {"XBOS_VN2_PREDEPLOY_MODE": "bootstrap",
                 "XBOS_VN2_BOOTSTRAP_AUTHORIZED": "true"}
    pd.predeploy(bootstrap)
    with pytest.raises(pd.AdmissionDenied, match="VN2_PRESTATE_NONEMPTY_OR_ACTIVE"):
        pd.predeploy(bootstrap)
    assert state["upgrades"] == 1


def test_bootstrap_rejects_partial_migration_without_upgrade(monkeypatch):
    monkeypatch.setattr(pd, "target_url", lambda env=None: "synthetic")
    monkeypatch.setattr(pd, "security_config", lambda env=None: None)
    conn = FakeConnection(tables={"alembic_version"}, public_objects=1)
    monkeypatch.setattr(pd, "check_database",
                        lambda url, ready=True: pd.check_schema(conn, ready))
    monkeypatch.setattr(pd.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("Unexpected second migration")))
    with pytest.raises(pd.AdmissionDenied):
        pd.predeploy({"XBOS_VN2_PREDEPLOY_MODE": "bootstrap",
                      "XBOS_VN2_BOOTSTRAP_AUTHORIZED": "true"})


@pytest.mark.parametrize("flag", [None, "", "false", "False", "TRUE", "1", "yes", "true "])
@pytest.mark.parametrize("route", [
    "/kernel/browser-session/v1/login",
    "/kernel/browser-session/v1/continue",
    "/kernel/platform/v1/pack-template-discovery",
    "/kernel/checkout",
    "/kernel/auth/me",
])
def test_public_release_default_denies_all_customer_routes(monkeypatch, flag, route):
    if flag is None:
        monkeypatch.delenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", raising=False)
    else:
        monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", flag)
    monkeypatch.setattr(guard, "_delegate", None)
    monkeypatch.setattr(guard, "check_database",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("Denied customer route tried database access")))
    monkeypatch.setattr(guard, "security_config",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("Denied customer route reached application")))
    result = asgi_call({"type": "http", "method": "POST", "path": route})
    assert result[0]["status"] == 503
    assert not any(k == b"set-cookie" for k, _ in result[0]["headers"])
    assert guard._delegate is None


@pytest.mark.parametrize("flag", [None, "false", "TRUE", "1"])
def test_public_release_denial_websocket_1008(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", raising=False)
    else:
        monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", flag)
    monkeypatch.setattr(guard, "_delegate", None)
    result = asgi_call({"type": "websocket", "path": "/kernel/browser-session/v1/login"})
    assert result == [{"type": "websocket.close", "code": 1008}]
    assert guard._delegate is None


def test_ready_health_is_separate_from_public_release(monkeypatch):
    monkeypatch.delenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", raising=False)
    monkeypatch.setattr(guard, "_delegate", None)
    readbacks = []
    monkeypatch.setattr(guard, "security_config", lambda: None)
    monkeypatch.setattr(guard, "target_url", lambda: "synthetic")
    monkeypatch.setattr(guard, "check_database",
                        lambda url, ready=True: readbacks.append((url, ready)))
    health = asgi_call({"type": "http", "method": "GET", "path": "/health"})
    assert health[0]["status"] == 200
    assert health[1]["body"] == b'{"status":"ready"}'
    customer = asgi_call({"type": "http", "method": "POST",
                          "path": "/kernel/browser-session/v1/login"})
    assert customer[0]["status"] == 503
    assert readbacks == [("synthetic", True)]
    assert guard._delegate is None


def test_unready_health_503_even_if_release_denied(monkeypatch):
    monkeypatch.delenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", raising=False)
    monkeypatch.setattr(guard, "_delegate", None)
    monkeypatch.setattr(guard, "security_config", lambda: None)
    monkeypatch.setattr(guard, "target_url", lambda: "synthetic")
    def unready(*a, **k):
        raise pd.AdmissionDenied("synthetic-unready")
    monkeypatch.setattr(guard, "check_database", unready)
    result = asgi_call({"type": "http", "path": "/health"})
    assert result[0]["status"] == 503
    assert guard._delegate is None


def test_exact_true_allows_delegation_only_after_readiness(monkeypatch):
    monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", "true")
    called = []
    async def app_delegate(scope, receive, send):
        called.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"synthetic"})
    monkeypatch.setattr(guard, "_delegate", app_delegate)
    monkeypatch.setattr(guard, "security_config", lambda: None)
    monkeypatch.setattr(guard, "target_url", lambda: "synthetic")
    monkeypatch.setattr(guard, "check_database", lambda url, ready=True: None)
    path = "/kernel/browser-session/v1/login"
    result = asgi_call({"type": "http", "path": path, "method": "POST"})
    assert result[0]["status"] == 200
    assert called == [path]


def test_release_denial_no_generic_import_even_if_cached(monkeypatch):
    monkeypatch.setenv("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED", "false")
    async def fail_delegate(*a, **kw):
        raise AssertionError("Denied traffic entered cached generic app")
    monkeypatch.setattr(guard, "_delegate", fail_delegate)
    result = asgi_call({"type": "http", "path": "/kernel/checkout"})
    assert result[0]["status"] == 503
