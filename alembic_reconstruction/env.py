from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy import pool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from core.persistence.database_config import resolve_database_url
from core.persistence.reconstruction_policy import validate_reconstruction_url


configured_url = config.get_main_option("sqlalchemy.url") or None
resolved_url = resolve_database_url(configured_url=configured_url)
reconstruction_url = validate_reconstruction_url(resolved_url)
MIGRATION_DATABASE_URL = reconstruction_url.render_as_string(hide_password=False)

# The candidate baseline is explicit SQL. It is not an autogenerate authority.
target_metadata = None


def _shared_context_options() -> dict:
    return {
        "target_metadata": target_metadata,
        "include_schemas": False,
        "version_table_schema": "public",
        "transaction_per_migration": True,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=MIGRATION_DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_shared_context_options(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        MIGRATION_DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            **_shared_context_options(),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
