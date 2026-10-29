"""Disposable FAKE PG17 evidence-only RLS and privilege qualification.

Creates a new temporary 127.0.0.1-only PostgreSQL cluster using PostgreSQL
17 binaries and local trust auth, with NO hosted DSN, credentials, tenant rows,
persistent roles/grants or source migrations. Full teardown is mandatory.
If a private disposable cluster cannot be started, tests SKIP, never fall back.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest


def _binary(name: str) -> str | None:
    if os.name == "nt":
        root = Path("C:/Program Files/PostgreSQL/17/bin")
        path = root / (name + ".exe")
        return str(path) if path.is_file() else None
    # Only use local PG17 tools explicitly discovered; no production URL.
    path = shutil.which(name)
    if path is None:
        return None
    version = subprocess.run(
        [path, "--version"], capture_output=True, text=True, timeout=8, check=False
    )
    return path if "17." in version.stdout else None


def _clean_env() -> dict[str, str]:
    # No inherited PGHOST/PGPORT/PGPASSWORD/PGSERVICE/PGUSER/etc.
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}


def _run(args: list[str], *, env: dict[str, str], timeout: int = 25) -> subprocess.CompletedProcess[str]:
    # On Windows pg_ctl start launches a child postgres service. If pg_ctl's
    # stdout/stderr are PIPEs, the server may inherit them, causing
    # communicate() to hang even after pg_ctl itself exits successfully.
    # Send only pg_ctl output to DEVNULL; psql still captures bounded output.
    if Path(args[0]).stem.lower() == "pg_ctl":
        return subprocess.run(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout, env=env, check=False,
        )
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


@pytest.fixture(scope="module")
def private_fake_pg17():
    initdb, ctl, psql = (_binary(x) for x in ("initdb", "pg_ctl", "psql"))
    if not all((initdb, ctl, psql)):
        pytest.skip("HOLD_NO_DISPOSABLE_LOCAL_PG17_BINARIES")
    env = _clean_env()
    # Acquiring this address only selects a loopback ephemeral port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="msar_wnd_fake_pg17_") as tmp:
        data = str(Path(tmp) / "pgdata")
        logfile = str(Path(tmp) / "pg.log")
        started = False
        try:
            setup = _run(
                [initdb, "-D", data, "-A", "trust", "-U", "msar_local",
                 "--no-instructions", "--no-sync"], env=env, timeout=35
            )
            if setup.returncode:
                pytest.skip("HOLD_LOCAL_PG17_INITDB_NOT_AVAILABLE")
            run = _run(
                [ctl, "-D", data, "-l", logfile, "-o",
                 f"-h 127.0.0.1 -p {port} -c max_connections=12",
                 "-w", "start"], env=env, timeout=35
            )
            if run.returncode:
                pytest.skip("HOLD_LOCAL_PG17_STARTUP_NOT_AVAILABLE")
            started = True

            def sql(query: str, user: str = "msar_local", *, ok: bool = True) -> str:
                # Explicit loopback-only connection; never reads any DSN.
                cp = _run(
                    [psql, "-X", "-h", "127.0.0.1", "-p", str(port),
                     "-U", user, "-d", "postgres", "-A", "-t",
                     "-v", "ON_ERROR_STOP=1", "-c", query],
                    env=env,
                    timeout=15,
                )
                if ok:
                    assert cp.returncode == 0, "HOLD_LOCAL_FAKE_PG_SQL_FAILURE"
                else:
                    assert cp.returncode != 0, "HOLD_UNAUTHORIZED_SELECT_ACCEPTED"
                return cp.stdout.strip()

            sql("""
CREATE ROLE msar_definer NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE msar_executor LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE msar_stranger LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE SCHEMA msar_ephemeral;
CREATE TABLE msar_ephemeral.scope_marker(
  tenant_id bigint PRIMARY KEY,
  fake_only boolean NOT NULL,
  active boolean NOT NULL
);
INSERT INTO msar_ephemeral.scope_marker VALUES
  (910001,true,true), (2,false,true);
ALTER TABLE msar_ephemeral.scope_marker ENABLE ROW LEVEL SECURITY;
ALTER TABLE msar_ephemeral.scope_marker FORCE ROW LEVEL SECURITY;
CREATE POLICY allow_fake_only ON msar_ephemeral.scope_marker
  FOR SELECT TO msar_definer
  USING (tenant_id=910001 AND fake_only IS TRUE);
GRANT USAGE ON SCHEMA msar_ephemeral TO msar_definer, msar_executor;
GRANT SELECT(tenant_id,fake_only,active) ON msar_ephemeral.scope_marker TO msar_definer;
CREATE FUNCTION msar_ephemeral.check_scope(approved_tenant bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,msar_ephemeral
AS $$ SELECT EXISTS(
  SELECT 1 FROM msar_ephemeral.scope_marker
  WHERE tenant_id=approved_tenant AND fake_only AND active
) $$;
ALTER FUNCTION msar_ephemeral.check_scope(bigint) OWNER TO msar_definer;
REVOKE ALL ON FUNCTION msar_ephemeral.check_scope(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION msar_ephemeral.check_scope(bigint) TO msar_executor;
""")
            yield sql
        finally:
            if started:
                shutdown = _run(
                    [ctl, "-D", data, "-m", "immediate", "-w", "stop"],
                    env=env, timeout=35
                )
                assert shutdown.returncode == 0, "HOLD_DISPOSABLE_PG17_SHUTDOWN_FAILED"
            # TemporaryDirectory removes the entire fake PG17 cluster.
            # No use of any existing local or hosted PostgreSQL instance.


def test_pg17_only_exact_synthetic_scope_passes(private_fake_pg17):
    sql = private_fake_pg17
    assert sql("SELECT msar_ephemeral.check_scope(910001)", "msar_executor") == "t"
    assert sql("SELECT msar_ephemeral.check_scope(2)", "msar_executor") == "f"
    assert sql("SELECT msar_ephemeral.check_scope(910002)", "msar_executor") == "f"


def test_pg17_executor_denied_base_select_and_foreign_execute(private_fake_pg17):
    sql = private_fake_pg17
    sql("SELECT tenant_id FROM msar_ephemeral.scope_marker", "msar_executor", ok=False)
    sql("SELECT msar_ephemeral.check_scope(910001)", "msar_stranger", ok=False)
    assert sql(
        "SELECT has_table_privilege('msar_executor','msar_ephemeral.scope_marker','SELECT')"
    ) == "f"
    assert sql(
        "SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb "
        "FROM pg_roles WHERE rolname='msar_definer'"
    ) == "f"


def test_pg17_definer_rls_and_privilege_revoke_rollback(private_fake_pg17):
    sql = private_fake_pg17
    # The attestation function owner is intentionally NOLOGIN. In this
    # disposable simulation only, superuser switches to it to prove RLS.
    rows = sql(
        "SET ROLE msar_definer; "
        "SELECT COUNT(*) FROM msar_ephemeral.scope_marker; "
        "RESET ROLE;"
    ).splitlines()
    assert "1" in rows  # one fake row only; tenant2 excluded by RLS
    result = sql("""
BEGIN;
REVOKE EXECUTE ON FUNCTION msar_ephemeral.check_scope(bigint) FROM msar_executor;
SELECT has_function_privilege('msar_executor',
  'msar_ephemeral.check_scope(bigint)','EXECUTE');
ROLLBACK;
SELECT has_function_privilege('msar_executor',
  'msar_ephemeral.check_scope(bigint)','EXECUTE');
""")
    assert result.splitlines()[-3:] == ["f", "ROLLBACK", "t"]
    assert sql("SELECT msar_ephemeral.check_scope(910001)", "msar_executor") == "t"
