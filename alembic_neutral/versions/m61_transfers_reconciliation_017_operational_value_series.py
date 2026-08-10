"""Install operational transfers and ordered reconciliation series."""
from pathlib import Path

from alembic import op

revision = "m61_transfers_reconciliation_017"
down_revision = "m60_operational_balance_authority_016"
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
    _execute("m61_operational_transfers_up.sql")


def downgrade() -> None:
    _execute("m61_operational_transfers_down.sql")
