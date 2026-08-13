"""Install canonical PC3 semantic and classification authority."""
from pathlib import Path
from alembic import op

revision = "pc3_semantic_authority_023"
down_revision = "pc2_party_authority_022"
branch_labels = None
depends_on = None

def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")

def upgrade() -> None:
    op.get_bind().exec_driver_sql(_sql("pc3_semantic_authority_up.sql"))

def downgrade() -> None:
    op.get_bind().exec_driver_sql(_sql("pc3_semantic_authority_down.sql"))
