"""Install tenant-defined financial dimensions and posting-context policies."""

from pathlib import Path

from alembic import op


revision = "m25_financial_dimensions_007"
down_revision = "m24_balanced_posting_006"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_script(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_script("m25_financial_dimensions_up.sql")


def downgrade() -> None:
    _execute_script("m25_financial_dimensions_down.sql")
