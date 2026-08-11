"""Install reconciliation windows, continuity, calendar attribution, and cascades."""
from pathlib import Path

from alembic import op

revision = "m62_reconciliation_windows_018"
down_revision = "m61_transfers_reconciliation_017"
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
    _execute("m62_reconciliation_windows_up.sql")


def downgrade() -> None:
    _execute("m62_reconciliation_windows_down.sql")
