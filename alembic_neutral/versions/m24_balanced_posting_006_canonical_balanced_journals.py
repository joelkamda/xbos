"""Install canonical balanced journal posting capacity.

Revision ID: m24_balanced_posting_006
Revises: m23_reversal_capacity_005
"""

from pathlib import Path

from alembic import op


revision = "m24_balanced_posting_006"
down_revision = "m23_reversal_capacity_005"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_script(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_script("m24_balanced_posting_up.sql")


def downgrade() -> None:
    _execute_script("m24_balanced_posting_down.sql")
