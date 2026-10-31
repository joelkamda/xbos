"""WND Austin TEST OIDC: separate credential-backed, least-privilege PostgreSQL connection.

No import of the shared database.engine, no fallback to DATABASE_URL, no
Render secret reads/logging. Every fresh connection is authenticated using its
own LOGIN role and checked before handling encrypted single-use tickets.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.pool import NullPool

from platform_admin.swes_google_oidc_r7 import OIDCHold

DATABASE = "wnd_xafpay_demo_austin_db"
WRITER_ENV = "SWES_OIDC_WRITER_DATABASE_URL"
ROLE_NAME = re.compile(r"^swes_oidc_[a-z0-9_]{2,48}$")
OWNER_ROLE = "wnd_xafpay_demo_austin_db_user"
OIDC_TABLE = "public.swes_pa_oidc_challenges"


def _validate_url(raw: str):
    if not isinstance(raw, str) or not raw.strip():
        raise OIDCHold("HOLD_OIDC_DEDICATED_WRITER_URL_ABSENT")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise OIDCHold("HOLD_OIDC_WRITER_URL_INVALID") from exc
    if (
        url.get_backend_name() != "postgresql"
        or url.database != DATABASE
        or not isinstance(url.username, str)
        or not ROLE_NAME.fullmatch(url.username)
        or url.username == OWNER_ROLE
        or not isinstance(url.password, str)
        or len(url.password) < 20
        or not isinstance(url.host, str) or not url.host
        or url.query.get("options")
    ):
        raise OIDCHold("HOLD_OIDC_WRITER_URL_UNTRUSTED")
    return url


def verify_writer_connection(conn, expected_user: str) -> None:
    """Fail closed on actual DB identity, actor flags, privilege inheritance and ACL."""
    try:
        role = conn.execute(text("""
            SELECT current_database() AS db, current_user AS actor,
                   session_user AS authenticated,
                   r.rolcanlogin, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
                   r.rolinherit, r.rolbypassrls
            FROM pg_roles r WHERE r.rolname = current_user
        """)).mappings().one()
        if (
            role["db"] != DATABASE
            or role["actor"] != expected_user
            or role["authenticated"] != expected_user
            or role["rolcanlogin"] is not True
            or any(role[k] is True for k in (
                "rolsuper", "rolcreatedb", "rolcreaterole", "rolinherit", "rolbypassrls"
            ))
        ):
            raise OIDCHold("HOLD_OIDC_WRITER_ROLE_NOT_RESTRICTED")
        memberships = conn.execute(text("""
            SELECT count(*) FROM pg_auth_members m
            JOIN pg_roles r ON r.oid=m.member
            WHERE r.rolname=:role
        """), {"role": expected_user}).scalar_one()
        if memberships != 0:
            raise OIDCHold("HOLD_OIDC_WRITER_INHERITED_ROLE")
        elevated = conn.execute(text("""
            SELECT has_database_privilege(current_user,current_database(),'CREATE')
              AS db_create,
                   has_schema_privilege(current_user,'public','CREATE')
              AS schema_create
        """)).mappings().one()
        if elevated["db_create"] or elevated["schema_create"]:
            raise OIDCHold("HOLD_OIDC_WRITER_DDL_PRIVILEGE")
        target = conn.execute(text(
            "SELECT to_regclass('public.swes_pa_oidc_challenges')"
        )).scalar_one()
        if target is None:
            raise OIDCHold("HOLD_OIDC_CHALLENGE_TABLE_UNMIGRATED")
        allowed = {
            "SELECT": True, "INSERT": True, "DELETE": True,
            "UPDATE": False, "TRUNCATE": False, "REFERENCES": False,
            "TRIGGER": False,
        }
        for privilege, permitted in allowed.items():
            actual = conn.execute(text("""
                SELECT has_table_privilege(current_user,
                    'public.swes_pa_oidc_challenges', :privilege)
            """), {"privilege": privilege}).scalar_one()
            if actual is not permitted:
                raise OIDCHold("HOLD_OIDC_WRITER_TABLE_ACL_MISMATCH")
        unrelated_access = conn.execute(text("""
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public'
              AND c.relkind IN ('r','p','v','m','f')
              AND c.relname!='swes_pa_oidc_challenges'
              AND (
                has_table_privilege(current_user,c.oid,'SELECT')
                OR has_table_privilege(current_user,c.oid,'INSERT')
                OR has_table_privilege(current_user,c.oid,'UPDATE')
                OR has_table_privilege(current_user,c.oid,'DELETE')
                OR has_table_privilege(current_user,c.oid,'TRUNCATE')
                OR has_table_privilege(current_user,c.oid,'REFERENCES')
                OR has_table_privilege(current_user,c.oid,'TRIGGER')
              )
        """)).scalar_one()
        if unrelated_access:
            raise OIDCHold("HOLD_OIDC_WRITER_UNRELATED_TABLE_ACCESS")
    except OIDCHold:
        raise
    except Exception as exc:
        raise OIDCHold("HOLD_OIDC_WRITER_IDENTITY_UNVERIFIABLE") from exc


def create_restricted_oidc_engine(*, url: str | None = None):
    """Uses only dedicated credential; validates each independent DB login."""
    target = _validate_url(url if url is not None else os.getenv(WRITER_ENV))
    engine = create_engine(
        target, poolclass=NullPool, pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "application_name": "swes_pa_oidc_test"},
    )
    expected = target.username

    @event.listens_for(engine, "engine_connect")
    def _verify_every_login(connection):
        # NullPool makes each operation use a new LOGIN connection.
        # SQLAlchemy executes parameterized queries with its native dialect.
        try:
            verify_writer_connection(connection, expected)
        finally:
            # Verification SELECTs implicitly begin a transaction. End it
            # before SQLChallengeStore starts its own atomic INSERT/DELETE.
            # Otherwise SQLAlchemy joins a rollback-only owner transaction.
            connection.rollback()

    try:
        # Preflight NOW rather than deferring invalid role/user until callback.
        with engine.connect():
            pass
    except OIDCHold:
        engine.dispose()
        raise
    except Exception as exc:
        engine.dispose()
        raise OIDCHold("HOLD_OIDC_DEDICATED_WRITER_CONNECT_FAILED") from exc
    return engine
