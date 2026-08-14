"""Install neutral SO4 procurement and supplier operations authority."""
from pathlib import Path
from alembic import op

revision="so4_procurement_supplier_operations_029"
down_revision="so3_inventory_stock_movement_028"
branch_labels=None
depends_on=None

def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try: cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally: cursor.close()

def upgrade(): _execute("so4_procurement_supplier_operations_up.sql")
def downgrade(): _execute("so4_procurement_supplier_operations_down.sql")
