"""Install neutral SO5 resource and operational assignment authority."""
from pathlib import Path
from alembic import op
revision="so5_resources_operational_assignment_030"
down_revision="so4_procurement_supplier_operations_029"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so5_resources_operational_assignment_up.sql")
def downgrade():_execute("so5_resources_operational_assignment_down.sql")
