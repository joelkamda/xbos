"""WND Austin TEST-only OIDC distinct LOGIN admission.

Endpoint mode prints non-secret connection location. Provision mode must have
an independently admitted Render-held writer credential, and creates ONLY the
restricted OIDC LOGIN with transactional grants and effective ACL validation.
Verification never enables Google login, PC5, merchant, or payment operations.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from platform_admin.swes_google_oidc_r7 import Challenge, digest
from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore
from platform_admin.swes_oidc_writer_r11 import create_restricted_oidc_engine

DB = "wnd_xafpay_demo_austin_db"
OWNER = "wnd_xafpay_demo_austin_db_user"
WRITER = "swes_oidc_austin_writer_r11"
LEGACY = "5c706797029a"
OIDC_HEAD = "swes_pa_oidc_challenges_001"


def controlled_urls(*, require_writer: bool):
    if os.environ.get("SWES_OIDC_ENABLED") != "false":
        raise RuntimeError("HOLD_OIDC_LOGIN_MUST_STAY_OFF")
    if os.environ.get("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED") != "0":
        raise RuntimeError("HOLD_CHECKOUT_MUST_STAY_OFF")
    owner_raw = os.environ.get("DATABASE_URL", "")
    if not owner_raw:
        raise RuntimeError("HOLD_OWNER_DB_CONNECTION_ABSENT")
    owner_url = make_url(owner_raw)
    if (
        owner_url.get_backend_name() != "postgresql"
        or owner_url.database != DB
        or owner_url.username != OWNER
        or not owner_url.host
    ):
        raise RuntimeError("HOLD_UNEXPECTED_OWNER_CONNECTION")
    writer_raw = os.environ.get("SWES_OIDC_WRITER_DATABASE_URL", "")
    if not require_writer:
        return owner_url, None
    if not writer_raw:
        raise RuntimeError("HOLD_RESTRICTED_WRITER_CREDENTIAL_NOT_CONFIGURED")
    writer_url = make_url(writer_raw)
    if (
        writer_url.get_backend_name() != "postgresql"
        or writer_url.username != WRITER
        or writer_url.database != DB
        or writer_url.host != owner_url.host
        or (writer_url.port or 5432) != (owner_url.port or 5432)
        or not writer_url.password
        or len(writer_url.password) < 32
        or writer_url.query.get("options")
    ):
        raise RuntimeError("HOLD_WRITER_CREDENTIAL_SCOPE_MISMATCH")
    return owner_url, writer_url


def owner_preflight(conn, *, expect_role: bool) -> None:
    row = conn.execute(text("""
        SELECT current_database() AS db,current_user AS actor,
          session_user AS login_actor,pg_is_in_recovery() AS replica,
          (SELECT version_num FROM public.alembic_version LIMIT 1) AS legacy,
          (SELECT version_num FROM public.alembic_version_swes_oidc LIMIT 1) AS oidc,
          EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:writer) AS role_exists
    """), {"writer": WRITER}).mappings().one()
    if (
        row["db"] != DB
        or row["actor"] != OWNER
        or row["login_actor"] != OWNER
        or row["replica"] is not False
        or row["legacy"] != LEGACY
        or row["oidc"] != OIDC_HEAD
        or row["role_exists"] is not expect_role
    ):
        raise RuntimeError("HOLD_R13_ROLE_PRESTATE_MISMATCH")


def role_acl(conn) -> None:
    role = conn.execute(text("""
        SELECT rolcanlogin,rolinherit,rolsuper,rolcreaterole,
          rolcreatedb,rolbypassrls
        FROM pg_roles WHERE rolname=:role
    """), {"role": WRITER}).mappings().one()
    if (
        role["rolcanlogin"] is not True
        or any(role[name] is True for name in (
            "rolinherit", "rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls"
        ))
    ):
        raise RuntimeError("HOLD_R13_WRITER_ELEVATED_ROLE_FLAGS")
    members = conn.execute(text("""
        SELECT count(*) FROM pg_auth_members m
        JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=:role
    """), {"role": WRITER}).scalar_one()
    if members:
        raise RuntimeError("HOLD_R13_WRITER_MEMBER_OF_OTHER_ROLES")
    ddl = conn.execute(text("""
        SELECT has_database_privilege(:role,current_database(),'CREATE') AS db_create,
               has_schema_privilege(:role,'public','CREATE') AS schema_create
    """), {"role": WRITER}).mappings().one()
    if ddl["db_create"] or ddl["schema_create"]:
        raise RuntimeError("HOLD_R13_WRITER_DDL_PRIVILEGE")
    for privilege, expected in (
        ("SELECT", True), ("INSERT", True), ("DELETE", True),
        ("UPDATE", False), ("TRUNCATE", False), ("REFERENCES", False),
        ("TRIGGER", False),
    ):
        value = conn.execute(text("""
            SELECT has_table_privilege(
                :role,'public.swes_pa_oidc_challenges',:privilege)
        """), {"role": WRITER, "privilege": privilege}).scalar_one()
        if value is not expected:
            raise RuntimeError("HOLD_R13_WRITER_OIDC_ACL_MISMATCH")
    unrelated = conn.execute(text("""
        SELECT count(*) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
          AND c.relname!='swes_pa_oidc_challenges'
          AND (
            has_table_privilege(:role,c.oid,'SELECT')
            OR has_table_privilege(:role,c.oid,'INSERT')
            OR has_table_privilege(:role,c.oid,'UPDATE')
            OR has_table_privilege(:role,c.oid,'DELETE')
            OR has_table_privilege(:role,c.oid,'TRUNCATE')
            OR has_table_privilege(:role,c.oid,'REFERENCES')
            OR has_table_privilege(:role,c.oid,'TRIGGER')
          )
    """), {"role": WRITER}).scalar_one()
    if unrelated:
        raise RuntimeError("HOLD_R13_WRITER_UNRELATED_RELATION_PRIVILEGES")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("endpoint", "provision", "verify", "replay"))
    parser.add_argument("--role-admission-attested", action="store_true")
    args = parser.parse_args()
    owner_url, writer_url = controlled_urls(
        require_writer=args.mode != "endpoint"
    )
    if args.mode == "endpoint":
        print("SWES_R13_DB_ENDPOINT_NONSECRET", {
            "host": owner_url.host, "port": owner_url.port or 5432,
            "db": owner_url.database, "owner_name": owner_url.username,
        }, flush=True)
        return
    if args.mode == "provision" and not args.role_admission_attested:
        raise RuntimeError("HOLD_R13_ROLE_ADMISSION_NOT_ATTESTED")

    engine = create_engine(owner_url, poolclass=NullPool)
    try:
        if args.mode == "provision":
            from psycopg2 import sql

            with engine.begin() as conn:
                owner_preflight(conn, expect_role=False)
                dbapi = conn.connection.driver_connection
                with dbapi.cursor() as cur:
                    cur.execute(sql.SQL(
                        "CREATE ROLE {} WITH LOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(WRITER), sql.Literal(writer_url.password)))
                    cur.execute(sql.SQL(
                        "GRANT USAGE ON SCHEMA public TO {}"
                    ).format(sql.Identifier(WRITER)))
                    cur.execute(sql.SQL(
                        "GRANT SELECT, INSERT, DELETE ON TABLE "
                        "public.swes_pa_oidc_challenges TO {}"
                    ).format(sql.Identifier(WRITER)))
                role_acl(conn)
            print("SWES_R13_RESTRICTED_ROLE_TRANSACTION_COMMITTED", flush=True)
        else:
            with engine.connect() as conn:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                owner_preflight(conn, expect_role=True)
                role_acl(conn)
                conn.rollback()
        # Independent real credential (no SET ROLE, no shared engine fallback).
        writer = create_restricted_oidc_engine(
            url=writer_url.render_as_string(hide_password=False)
        )
        try:
            with writer.connect() as conn:
                actor = conn.execute(text(
                    "SELECT current_user AS role,session_user AS authenticated"
                )).mappings().one()
                if actor["role"] != WRITER or actor["authenticated"] != WRITER:
                    raise RuntimeError("HOLD_R13_NOT_DISTINCT_DB_LOGIN")
            print("SWES_R13_ACTUAL_PASSWORD_LOGIN_AND_LEAST_PRIVILEGE_PASS", flush=True)
            if args.mode == "replay":
                import secrets

                from cryptography.fernet import Fernet

                store = SQLChallengeStore(
                    writer, fernet_key=Fernet.generate_key().decode("ascii")
                )
                now = datetime.now(timezone.utc).replace(microsecond=0)
                challenge = Challenge(
                    digest(secrets.token_urlsafe(24)), digest(secrets.token_urlsafe(24)),
                    "R13-TEST-ONLY-OPAQUE-VERIFIER", now,
                    now + timedelta(minutes=5),
                )
                store.issue(challenge)
                if store.consume(challenge.state_digest) != challenge:
                    raise RuntimeError("HOLD_R13_TICKET_REDEEM_MISMATCH")
                if store.consume(challenge.state_digest) is not None:
                    raise RuntimeError("HOLD_R13_TICKET_REPLAY_ACCEPTED")
                print("SWES_R13_HOSTED_ENCRYPTED_TICKET_SINGLE_USE_PASS", flush=True)
        finally:
            writer.dispose()
    except Exception:  # noqa: BLE001 - redact possible SQL credential details
        # Never allow a PostgreSQL exception/SQL-Literal containing password
        # material into Render job logs or a PCR record.
        raise RuntimeError("HOLD_R13_RESTRICTED_LOGIN_ADMISSION_FAILED") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
