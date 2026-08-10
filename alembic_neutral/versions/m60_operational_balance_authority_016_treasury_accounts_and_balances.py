"""Install operational-account and expected/actual balance authority."""
from pathlib import Path

from alembic import op

revision = "m60_operational_balance_authority_016"
down_revision = "m46_provider_financials_015"
branch_labels = None
depends_on = None
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_sql(sql: str) -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def _execute(name: str) -> None:
    _execute_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_sql(
        "ALTER TABLE public.alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(255)"
    )
    _execute("m60_operational_balance_authority_up.sql")


def downgrade() -> None:
    # Keep migration metadata widened while Alembic still stores this revision.
    _execute("m60_operational_balance_authority_down.sql")
