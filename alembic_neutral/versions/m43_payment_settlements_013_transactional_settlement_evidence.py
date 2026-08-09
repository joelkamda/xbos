"""Activate transactional settlement evidence and reversal capacity.

Revision ID: m43_payment_settlements_013
Revises: m42_payment_attempts_012
"""

from pathlib import Path

from alembic import op


revision = "m43_payment_settlements_013"
down_revision = "m42_payment_attempts_012"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("m43_payment_settlements_up.sql")


def downgrade() -> None:
    _execute("m43_payment_settlements_down.sql")
