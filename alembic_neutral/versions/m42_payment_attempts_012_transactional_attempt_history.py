"""Activate transactional payment attempts and append-only attempt history.

Revision ID: m42_payment_attempts_012
Revises: m40_payment_foundation_011
"""

from pathlib import Path

from alembic import op


revision = "m42_payment_attempts_012"
down_revision = "m40_payment_foundation_011"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("m42_payment_attempts_up.sql")


def downgrade() -> None:
    _execute("m42_payment_attempts_down.sql")
