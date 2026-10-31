"""SWES R11: isolated WND OIDC migration on disposable PG17 only."""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from alembic import command

ROOT = Path(__file__).resolve().parents[2]
PG = Path("C:/Program Files/PostgreSQL/17/bin")
DB = "wnd_xafpay_demo_austin_db"
USER = "swes_r11_test_admin"
HEAD = "swes_pa_oidc_challenges_001"


def _run(args, env):
    result = subprocess.run(
        args, env=env, timeout=180, check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert result.returncode == 0, ("PG17_DISPOSABLE_STEP_HOLD", args[0])


def _config():
    return Config(str(ROOT / "alembic_swes_oidc.ini"))


def test_schema_guards_refuse_no_approval_and_wrong_db(monkeypatch):
    monkeypatch.delenv("SWES_OIDC_SCHEMA_ACTION", raising=False)
    monkeypatch.setenv(
        "SWES_WND_OIDC_TEST_DB_URL",
        "postgresql+psycopg2://nobody@127.0.0.1:1/" + DB,
    )
    with pytest.raises(RuntimeError, match="SCHEMA_APPROVAL_HOLD"):
        command.upgrade(_config(), "head")

    monkeypatch.setenv("SWES_OIDC_SCHEMA_ACTION", "SWES_OIDC_TEST_910001_SCHEMA_EXPLICIT")
    monkeypatch.setenv(
        "SWES_WND_OIDC_TEST_DB_URL",
        "postgresql+psycopg2://nobody@127.0.0.1:1/production_wnd",
    )
    with pytest.raises(RuntimeError, match="EXACT_TEST_DATABASE_REQUIRED"):
        command.upgrade(_config(), "head")

    monkeypatch.setenv(
        "SWES_WND_OIDC_TEST_DB_URL",
        "postgresql+psycopg2://nobody@127.0.0.1:1/" + DB,
    )
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    with pytest.raises(RuntimeError, match="LOGIN_MUST_BE_DISABLED"):
        command.upgrade(_config(), "head")


def test_isolated_oidc_migration_upgrade_acl_guarded_downgrade_pg17(monkeypatch):
    if not all((PG / name).is_file() for name in ("initdb.exe", "pg_ctl.exe", "psql.exe")):
        pytest.skip("local PostgreSQL17 binaries unavailable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # This fixture never accepts an existing DB URL, port, or cluster.
    pg_env = {key: value for key, value in os.environ.items()
              if not key.upper().startswith("PG")
              and key.upper() not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}}
    with tempfile.TemporaryDirectory(prefix="swes_r11_oidc_only_pg17_") as tmp:
        data = Path(tmp) / "data"
        log = Path(tmp) / "server.log"
        started = False
        try:
            _run([str(PG / "initdb.exe"), "-D", str(data), "-A", "trust",
                  "-U", USER, "--no-instructions", "--no-sync"], pg_env)
            _run([str(PG / "pg_ctl.exe"), "-D", str(data), "-l", str(log),
                  "-o", f"-h 127.0.0.1 -p {port} -c max_connections=20",
                  "-w", "start"], pg_env)
            started = True
            _run([str(PG / "psql.exe"), "-X", "-h", "127.0.0.1",
                  "-p", str(port), "-U", USER, "-d", "postgres",
                  "-v", "ON_ERROR_STOP=1", "-c",
                  f'CREATE DATABASE "{DB}"'], pg_env)
            url = f"postgresql+psycopg2://{USER}@127.0.0.1:{port}/{DB}"
            monkeypatch.setenv("SWES_WND_OIDC_TEST_DB_URL", url)
            monkeypatch.setenv(
                "SWES_OIDC_SCHEMA_ACTION", "SWES_OIDC_TEST_910001_SCHEMA_EXPLICIT"
            )
            monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
            monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0")
            engine = create_engine(url)
            try:
                # Model live WND's separate, non-neutral version identity.
                with engine.begin() as c:
                    c.exec_driver_sql(
                        "CREATE TABLE public.alembic_version "
                        "(version_num VARCHAR(64) NOT NULL)"
                    )
                    c.execute(
                        text("INSERT INTO public.alembic_version (version_num) VALUES (:v)"),
                        {"v": "5c706797029a"},
                    )
                command.upgrade(_config(), "head")
                with engine.connect() as c:
                    assert c.execute(text(
                        "SELECT version_num FROM public.alembic_version"
                    )).scalar_one() == "5c706797029a"
                    assert c.execute(text(
                        "SELECT version_num FROM public.alembic_version_swes_oidc"
                    )).scalar_one() == HEAD
                    assert c.execute(text(
                        "SELECT count(*) FROM public.swes_pa_oidc_challenges"
                    )).scalar_one() == 0
                from cryptography.fernet import Fernet

                from platform_admin.swes_google_oidc_r7 import Challenge, digest
                from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore

                role = "swes_r11_restricted_writer"
                with engine.begin() as c:
                    c.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN")
                    c.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
                    c.exec_driver_sql(
                        f"GRANT SELECT, INSERT, DELETE ON "
                        f"public.swes_pa_oidc_challenges TO {role}"
                    )
                    for privilege, expected in (
                        ("SELECT", True), ("INSERT", True), ("DELETE", True),
                        ("UPDATE", False), ("TRUNCATE", False), ("REFERENCES", False),
                    ):
                        actual = c.execute(text(
                            "SELECT has_table_privilege(:role,"
                            "'public.swes_pa_oidc_challenges',:priv)"
                        ), {"role": role, "priv": privilege}).scalar_one()
                        assert actual is expected, (privilege, actual)

                now = datetime.now(timezone.utc)
                challenge = Challenge(
                    digest("r11-local-state"), digest("r11-local-nonce"),
                    "local-only-opaque-verifier", now, now + timedelta(minutes=5),
                )
                store = SQLChallengeStore(
                    engine, fernet_key=Fernet.generate_key().decode("ascii")
                )
                store.issue(challenge)
                try:
                    command.downgrade(_config(), "base")
                except SQLAlchemyError as exc:
                    assert "HOLD_OIDC_CHALLENGES_PENDING" in str(exc)
                else:
                    raise AssertionError("DOWNGRADE_DROPPED_PENDING_OIDC_TICKET")
                assert store.consume(challenge.state_digest) == challenge
                assert store.consume(challenge.state_digest) is None
                command.downgrade(_config(), "base")
                with engine.connect() as c:
                    assert c.execute(text(
                        "SELECT to_regclass('public.swes_pa_oidc_challenges')"
                    )).scalar_one() is None
                    assert c.execute(text(
                        "SELECT version_num FROM public.alembic_version"
                    )).scalar_one() == "5c706797029a"
                command.upgrade(_config(), "head")
                with engine.connect() as c:
                    assert c.execute(text(
                        "SELECT version_num FROM public.alembic_version_swes_oidc"
                    )).scalar_one() == HEAD
                print("SWES_R11_OIDC_ISOLATED_UP_DOWN_REINSTALL_PG17=PASS")
                print("SWES_R11_OIDC_LEGACY_WND_REVISION_PRESERVED=PASS")
                print("SWES_R11_OIDC_RESTRICTED_ROLE_AND_PENDING_GUARD=PASS")
            finally:
                engine.dispose()
        finally:
            if started:
                _run([str(PG / "pg_ctl.exe"), "-D", str(data),
                      "-m", "immediate", "-w", "stop"], pg_env)
    print("SWES_R11_OIDC_DISPOSABLE_PG17_CLEANUP=PASS")
