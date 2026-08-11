"""Install shared bank, A/R, and A/P reconciliation controls."""
from pathlib import Path

from alembic import op

revision = "m64_reconciliation_controls_020"
down_revision = "m63_reconciliation_close_019"
branch_labels = None
depends_on = None
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    finally:
        cursor.close()


def upgrade() -> None:
    _execute("m64_reconciliation_controls_up.sql")


def downgrade() -> None:
    _execute("m64_reconciliation_controls_down.sql")
