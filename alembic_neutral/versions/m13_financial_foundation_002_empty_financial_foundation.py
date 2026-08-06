"""Install the empty neutral financial structural foundation.

Revision ID: m13_financial_foundation_002
Revises: m13_source_state_001
"""

from pathlib import Path

from alembic import op


revision = "m13_financial_foundation_002"
down_revision = "m13_source_state_001"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "sql" / name
    if not path.is_file():
        raise RuntimeError(f"M1.3 SQL asset is missing: {path}")
    return path.read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(_sql("m13_financial_foundation_up.sql"))


def downgrade() -> None:
    op.execute(_sql("m13_financial_foundation_down.sql"))
