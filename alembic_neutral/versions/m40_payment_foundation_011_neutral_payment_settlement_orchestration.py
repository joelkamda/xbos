"""Install the empty neutral payment and settlement orchestration foundation."""

from pathlib import Path

from alembic import op


revision = "m40_payment_foundation_011"
down_revision = "m34_obligation_aging_010"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_script(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_script("m40_payment_foundation_up.sql")


def downgrade() -> None:
    _execute_script("m40_payment_foundation_down.sql")
