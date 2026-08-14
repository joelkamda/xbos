"""Adopt legacy inventory as neutral SO3 stock movement authority."""
from pathlib import Path
from alembic import op

revision = "so3_inventory_stock_movement_028"
down_revision = "so2_operational_party_relationships_027"
branch_labels = None
depends_on = None


def _execute(name):
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8"))
    finally:
        cursor.close()


def upgrade():
    _execute("so3_inventory_stock_movement_up.sql")


def downgrade():
    _execute("so3_inventory_stock_movement_down.sql")
