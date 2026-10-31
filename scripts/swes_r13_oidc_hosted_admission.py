"""WND Austin TEST-only OIDC: inspect/apply isolated schema via private Render job.

Never run on physical WND or on a neutral Alembic graph. The apply command
requires a separately verified snapshot/export, PITR and operator grant; its
CLI acknowledgement is not evidence that these external gates were satisfied.
No role creation, credentials, merchant/order data or payment actions here.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "wnd_xafpay_demo_austin_db"
OWNER = "wnd_xafpay_demo_austin_db_user"
LEGACY = "5c706797029a"
OIDC_HEAD = "swes_pa_oidc_challenges_001"
VERSION_NAME = "public.alembic_version_swes_oidc"
CHALLENGE_NAME = "public.swes_pa_oidc_challenges"
ROLE_NAME = "swes_oidc_austin_writer_r11"


def require_scope() -> str:
    if os.environ.get("SWES_OIDC_ENABLED") != "false":
        raise RuntimeError("HOLD_OIDC_LOGIN_NOT_EXPLICITLY_OFF")
    if os.environ.get("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED") != "0":
        raise RuntimeError("HOLD_CHECKOUT_NOT_EXPLICITLY_OFF")
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("HOLD_WND_DATABASE_CREDENTIAL_ABSENT")
    return url


def snapshot(url: str) -> dict:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '5000ms'")
            conn.exec_driver_sql("SET LOCAL lock_timeout = '500ms'")
            row = conn.execute(text("""
                SELECT current_database() AS db, current_user AS actor,
                  session_user AS authenticated, pg_is_in_recovery() AS replica,
                  (SELECT version_num FROM public.alembic_version LIMIT 1) AS legacy,
                  to_regclass('public.swes_pa_oidc_challenges') IS NOT NULL AS tickets,
                  to_regclass('public.alembic_version_swes_oidc') IS NOT NULL AS version,
                  EXISTS(SELECT 1 FROM pg_roles
                         WHERE rolname='swes_oidc_austin_writer_r11') AS restricted_role,
                  has_schema_privilege(current_user,'public','CREATE') AS can_create
            """)).mappings().one()
            state = dict(row)
            if (
                state["db"] != DATABASE
                or state["actor"] != OWNER
                or state["authenticated"] != OWNER
                or state["replica"] is not False
                or state["legacy"] != LEGACY
                or state["can_create"] is not True
            ):
                raise RuntimeError("HOLD_WND_R13_IDENTITY_OR_LEGACY_MISMATCH")
            if state["tickets"] != state["version"]:
                raise RuntimeError("HOLD_WND_R13_PARTIAL_SCHEMA_PRESTATE")
            if state["version"]:
                state["oidc_head"] = conn.execute(text(
                    "SELECT version_num FROM public.alembic_version_swes_oidc LIMIT 1"
                )).scalar_one()
                if state["oidc_head"] != OIDC_HEAD:
                    raise RuntimeError("HOLD_WND_R13_OIDC_VERSION_MISMATCH")
                state["challenge_count"] = int(conn.execute(text(
                    "SELECT count(*) FROM public.swes_pa_oidc_challenges"
                )).scalar_one())
            conn.rollback()
            return state
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "apply", "verify"))
    parser.add_argument(
        "--recovery-attested", action="store_true",
        help="Operator has separately verified export, usable PITR and recovery path.",
    )
    args = parser.parse_args()
    url = require_scope()
    before = snapshot(url)
    print("SWES_R13_OIDC_PRESTATE", {
        key: before[key]
        for key in ("db", "actor", "legacy", "tickets", "version", "restricted_role")
    }, flush=True)
    if args.mode == "preflight":
        if before["tickets"] or before["version"] or before["restricted_role"]:
            raise RuntimeError("HOLD_R13_SCHEMA_OR_ROLE_ALREADY_PRESENT")
        print("SWES_R13_EXACT_HOSTED_READONLY_PREFLIGHT_PASS", flush=True)
        return

    if args.mode == "verify":
        if not before["tickets"] or not before["version"]:
            raise RuntimeError("HOLD_R13_SCHEMA_NOT_YET_INSTALLED")
        print("SWES_R13_ISOLATED_SCHEMA_HOSTED_VERIFIED", {
            "legacy_unchanged": before["legacy"] == LEGACY,
            "oidc_head": before["oidc_head"],
            "pending_tickets": before["challenge_count"],
            "restricted_role_present": before["restricted_role"],
        }, flush=True)
        return

    if not args.recovery_attested:
        raise RuntimeError("HOLD_R13_RECOVERY_OPERATOR_ATTESTATION_REQUIRED")
    if before["tickets"] or before["version"] or before["restricted_role"]:
        raise RuntimeError("HOLD_R13_NONEMPTY_MIGRATION_PRESTATE")
    # Guarded per-process context; no persistent environment changes. Alembic
    # has a DIFFERENT version table, and uses its own transaction/rollback.
    os.environ["SWES_OIDC_SCHEMA_ACTION"] = "SWES_OIDC_TEST_910001_SCHEMA_EXPLICIT"
    os.environ["SWES_WND_OIDC_TEST_DB_URL"] = url
    command.upgrade(Config(str(ROOT / "alembic_swes_oidc.ini")), "head")
    after = snapshot(url)
    if not after["tickets"] or not after["version"] or after["challenge_count"] != 0:
        raise RuntimeError("HOLD_R13_SCHEMA_APPLY_POSTSTATE_MISMATCH")
    if after["restricted_role"]:
        raise RuntimeError("HOLD_R13_UNEXPECTED_ROLE_MUTATION")
    print("SWES_R13_ISOLATED_SCHEMA_APPLY_PASS", {
        "legacy_unchanged": True,
        "oidc_head": after["oidc_head"],
        "new_tickets": after["challenge_count"],
        "role_created": False,
    }, flush=True)


if __name__ == "__main__":
    main()
