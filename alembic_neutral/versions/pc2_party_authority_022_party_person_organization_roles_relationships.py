"""Install canonical PC2 Party authority.

Revision ID: pc2_party_authority_022
Revises: pc1_structural_context_021
"""

from pathlib import Path

from alembic import op

revision = "pc2_party_authority_022"
down_revision = "pc1_structural_context_021"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_sql("pc2_party_authority_up.sql"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(_sql("pc2_party_authority_down.sql"))
