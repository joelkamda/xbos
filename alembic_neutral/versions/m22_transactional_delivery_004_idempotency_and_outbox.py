"""Align command idempotency and the transactional outbox.

Revision ID: m22_transactional_delivery_004
Revises: m20_event_catalog_003
"""

from pathlib import Path

from alembic import op


revision = "m22_transactional_delivery_004"
down_revision = "m20_event_catalog_003"
branch_labels = None
depends_on = None


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_script(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute_script("m22_transactional_delivery_up.sql")


def downgrade() -> None:
    _execute_script("m22_transactional_delivery_down.sql")
