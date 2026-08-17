"""Pre-R0 semantic classification hardening: global taxonomy, history, overlays and governed assignments."""
from pathlib import Path
from alembic import op

revision = "semantic_classification_hardening_041"
down_revision = "pa45_support_recovery_health_040"
branch_labels = None
depends_on = None


def _execute(name: str) -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8"))
    finally:
        cursor.close()


def upgrade() -> None:
    _execute("semantic_classification_hardening_up.sql")


def downgrade() -> None:
    _execute("semantic_classification_hardening_down.sql")
