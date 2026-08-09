"""Activate tender composition and supported payment patterns.

Revision ID: m44_payment_patterns_014
Revises: m43_payment_settlements_013
"""
from pathlib import Path
from alembic import op

revision = "m44_payment_patterns_014"
down_revision = "m43_payment_settlements_013"
branch_labels = None
depends_on = None
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))

def upgrade() -> None:
    _execute("m44_payment_patterns_up.sql")

def downgrade() -> None:
    _execute("m44_payment_patterns_down.sql")
