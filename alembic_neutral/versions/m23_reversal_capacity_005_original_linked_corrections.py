"""Enforce original-linked correction type and cumulative capacity.

Revision ID: m23_reversal_capacity_005
Revises: m22_transactional_delivery_004
"""

from pathlib import Path

from alembic import op


revision = "m23_reversal_capacity_005"
down_revision = "m22_transactional_delivery_004"
branch_labels = None
depends_on = None


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_script(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_script("m23_reversal_capacity_up.sql")


def downgrade() -> None:
    _execute_script("m23_reversal_capacity_down.sql")
