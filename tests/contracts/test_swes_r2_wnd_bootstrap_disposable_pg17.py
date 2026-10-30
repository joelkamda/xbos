"""Source-faithful SWES TEST fixture rehearsal on disposable loopback PG17 ONLY.

Creates a temporary local PGDATA and database, replays neutral migrations,
proves atomic rollback on injected SQL failure, verifies exact successful
fixture and duplicate refusal, and shuts down the temporary cluster.
Never connects to Render and never calls providers.
"""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, text

from alembic import command
from scripts import swes_r2_wnd_synthetic_fixture_bootstrap as target

ROOT = Path(__file__).resolve().parents[2]
PG = Path("C:/Program Files/PostgreSQL/17/bin")
DB = "swes_r2_wnd_bootstrap_disposable"
USER = "swes_r2_local"


def _run(args: list[str], env: dict[str, str], timeout=180) -> None:
    # pg_ctl spawns a server that may inherit output handles on Windows.
    # DEVNULL avoids holding subprocess.run's capture pipes open indefinitely.
    if Path(args[0]).stem.lower() == "pg_ctl":
        proc = subprocess.run(args, env=env, check=False, timeout=timeout,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stderr = ""
    else:
        proc = subprocess.run(args, env=env, check=False, timeout=timeout,
                              capture_output=True, text=True)
        stderr = proc.stderr
    if proc.returncode:
        raise RuntimeError("SWES_LOCAL_SUBPROCESS_FAILED: "
                           + Path(args[0]).name + " " + stderr[-800:])


@pytest.fixture(scope="module")
def disposable_url():
    for binary in ("initdb.exe", "pg_ctl.exe", "psql.exe"):
        if not (PG / binary).is_file():
            pytest.skip("local PG17 binary unavailable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        key: val for key, val in os.environ.items()
        if not key.upper().startswith("PG")
        and key.upper() not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    with tempfile.TemporaryDirectory(prefix="swes_r2_disposable_pg17_") as temp:
        pgdata = str(Path(temp) / "pgdata")
        log = str(Path(temp) / "postgres.log")
        started = False
        try:
            _run([str(PG / "initdb.exe"), "-D", pgdata, "-A", "trust",
                  "-U", USER, "--no-instructions", "--no-sync"], env)
            _run([str(PG / "pg_ctl.exe"), "-D", pgdata, "-l", log, "-o",
                  f"-h 127.0.0.1 -p {port} -c max_connections=20",
                  "-w", "start"], env)
            started = True
            _run([str(PG / "psql.exe"), "-X", "-h", "127.0.0.1",
                  "-p", str(port), "-U", USER, "-d", "postgres",
                  "-v", "ON_ERROR_STOP=1",
                  "-c", f'CREATE DATABASE "{DB}"'], env)
            url = f"postgresql+psycopg://{USER}@127.0.0.1:{port}/{DB}"
            config = Config(str(ROOT / "alembic_neutral.ini"))
            previous = {name: os.environ.get(name)
                        for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL",
                                     "ALEMBIC_NEUTRAL_VERSION_TABLE")}
            try:
                os.environ["DATABASE_URL"] = url
                os.environ["MIGRATION_DATABASE_URL"] = url
                os.environ["ALEMBIC_NEUTRAL_VERSION_TABLE"] = "alembic_version"
                command.upgrade(config, "head")
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            engine = create_engine(url)
            try:
                with engine.connect() as conn:
                    head = conn.execute(text(
                        "SELECT version_num FROM public.alembic_version"
                    )).scalar_one()
                assert head == "cc_order_draft_facade_050"
            finally:
                engine.dispose()
            yield url
        finally:
            if started:
                _run([str(PG / "pg_ctl.exe"), "-D", pgdata,
                      "-m", "immediate", "-w", "stop"], env)


def test_source_faithful_pg17_atomic_bootstrap(disposable_url, monkeypatch):
    original = target.create_engine
    before = target.execute(disposable_url, "dry-run", hosted=False)
    assert all(count == 0 for count in before["before"].values())

    instrumented = original(disposable_url)
    def inject_failure(_conn, _cursor, statement, _params, _context, _many):
        if "INSERT INTO public.so1_prices" in statement:
            raise RuntimeError("SWES_DISPOSABLE_ROLLBACK_INJECTION")
    event.listen(instrumented, "before_cursor_execute", inject_failure)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(target, "create_engine", lambda *_a, **_k: instrumented)
            with pytest.raises(RuntimeError, match="ROLLBACK_INJECTION"):
                target.execute(disposable_url, "apply", hosted=False)
    finally:
        event.remove(instrumented, "before_cursor_execute", inject_failure)
        instrumented.dispose()

    after_fault = target.execute(disposable_url, "dry-run", hosted=False)
    assert after_fault["before"] == before["before"]

    applied = target.execute(disposable_url, "apply", hosted=False)
    assert applied["after"]["tenants"] == 1
    assert applied["after"]["pa_merchants"] == 1
    assert applied["after"]["so1_prices"] == 1
    assert applied["after"]["restaurant_customer_catalog_read_bindings"] == 1
    assert applied["after"]["service_identities"] == 0
    assert applied["after"]["r1_restaurant_orders"] == 0
    assert applied["price"] == {"currency": "XAF", "amount": 1000}
    assert applied["merchant_state"] == "registered"
    with pytest.raises(RuntimeError, match="CANDIDATE_TENANT_NOT_EMPTY"):
        target.execute(disposable_url, "apply", hosted=False)

    eng = original(disposable_url)
    try:
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT m.administration_state, p.currency, p.amount "
                "FROM public.pa_merchants m "
                "JOIN public.restaurant_customer_catalog_read_bindings b "
                "ON b.merchant_public_id=m.public_id "
                "JOIN public.so1_catalogs c ON c.public_id=b.catalog_public_id "
                "JOIN public.so1_catalog_entries e ON e.catalog_id=c.id "
                "JOIN public.so1_prices p ON p.tenant_id=e.tenant_id "
                "AND p.atomic_unit_id=e.atomic_unit_id "
                "AND p.price_code=b.price_code "
                "WHERE m.tenant_id=:tenant"
            ), {"tenant": target.TENANT}).one()
            assert row.administration_state == "registered"
            assert row.currency == "XAF"
            assert row.amount == 1000
    finally:
        eng.dispose()
