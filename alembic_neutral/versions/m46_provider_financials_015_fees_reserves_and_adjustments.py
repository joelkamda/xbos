"""Install provider fee, reserve, adjustment, and net-position authority."""
from pathlib import Path

from alembic import op

revision = "m46_provider_financials_015"
down_revision = "m44_payment_patterns_014"
branch_labels = None
depends_on = None
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute(name):
    op.get_bind().exec_driver_sql((SQL_DIR / name).read_text(encoding="utf-8"))


def upgrade():
    _execute("m46_provider_financials_up.sql")


def downgrade():
    _execute("m46_provider_financials_down.sql")
