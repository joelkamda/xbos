"""Add append-only obligation lifecycle history for deterministic as-of aging."""

from pathlib import Path
from alembic import op

revision="m34_obligation_aging_010"
down_revision="m32_allocation_engine_009"
branch_labels=None
depends_on=None
SQL_DIR=Path(__file__).resolve().parents[1]/"sql"


def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((SQL_DIR/name).read_text(encoding="utf-8"))


def upgrade() -> None: _execute("m34_obligation_aging_up.sql")
def downgrade() -> None: _execute("m34_obligation_aging_down.sql")
