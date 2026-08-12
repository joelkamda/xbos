"""Install PC1 canonical tenant and structural-context authority."""

from pathlib import Path
from alembic import op

revision = "pc1_structural_context_021"
down_revision = "m64_reconciliation_controls_020"
branch_labels = None
depends_on = None


def _execute(name: str) -> None:
    op.execute((Path(__file__).parents[1] / "sql" / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("pc1_structural_context_up.sql")


def downgrade() -> None:
    _execute("pc1_structural_context_down.sql")
