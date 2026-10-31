"""Isolated SWES WND Austin OIDC migrations; no connection without exact gates."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from alembic import context

DB = "wnd_xafpay_demo_austin_db"
VERSION_TABLE = "alembic_version_swes_oidc"
ACTION = "SWES_OIDC_TEST_910001_SCHEMA_EXPLICIT"

if context.is_offline_mode():
    raise RuntimeError("SWES_OIDC_OFFLINE_MIGRATION_FORBIDDEN")

if os.environ.get("SWES_OIDC_SCHEMA_ACTION") != ACTION:
    raise RuntimeError("SWES_OIDC_SCHEMA_APPROVAL_HOLD")
if os.environ.get("SWES_OIDC_ENABLED", "false") != "false":
    raise RuntimeError("SWES_OIDC_LOGIN_MUST_BE_DISABLED")
if os.environ.get("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0") not in ("", "0"):
    raise RuntimeError("SWES_OIDC_CHECKOUT_MUST_BE_DISABLED")

raw_url = os.environ.get("SWES_WND_OIDC_TEST_DB_URL")
if not raw_url:
    raise RuntimeError("SWES_OIDC_EXPLICIT_DB_URL_REQUIRED")
parsed = make_url(raw_url)
if parsed.get_backend_name() != "postgresql" or parsed.database != DB:
    raise RuntimeError("SWES_OIDC_EXACT_TEST_DATABASE_REQUIRED")

# Never reuse the WND neutral Alembic graph or its alembic_version table.
engine = create_engine(raw_url, poolclass=NullPool)
try:
    # The initial identity SELECT opens a transaction implicitly. Own and
    # commit the entire migration on success; rollback all DDL on failure.
    with engine.begin() as conn:
        if conn.execute(text("SELECT current_database()")).scalar_one() != DB:
            raise RuntimeError("SWES_OIDC_DATABASE_IDENTITY_HOLD")
        if conn.execute(text("SELECT pg_is_in_recovery()")).scalar_one():
            raise RuntimeError("SWES_OIDC_READ_REPLICA_HOLD")
        context.configure(
            connection=conn, target_metadata=None,
            version_table=VERSION_TABLE, version_table_schema="public",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
