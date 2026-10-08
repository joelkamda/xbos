from logging.config import fileConfig
import os
from pathlib import Path
import re
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    from database import DATABASE_URL as database_url

config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
neutral_version_table = os.environ.get(
    "ALEMBIC_NEUTRAL_VERSION_TABLE",
    "alembic_version",
)
if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", neutral_version_table) is None:
    raise RuntimeError("invalid_alembic_neutral_version_table")
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=neutral_version_table,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=neutral_version_table,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
