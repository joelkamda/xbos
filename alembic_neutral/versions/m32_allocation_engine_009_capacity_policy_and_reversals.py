"""Activate governed value allocation, capacity, and reversal authority."""

from pathlib import Path
from alembic import op

revision = "m32_allocation_engine_009"
down_revision = "m30_obligation_foundation_008"
branch_labels = None
depends_on = None
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("m32_allocation_engine_up.sql")


def downgrade() -> None:
    _execute("m32_allocation_engine_down.sql")
