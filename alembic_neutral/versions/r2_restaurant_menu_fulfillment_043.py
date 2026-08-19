"""Install R2 Restaurant menu and fulfillment authority."""
from pathlib import Path
from alembic import op
revision='r2_restaurant_menu_fulfillment_043'
down_revision='r1_restaurant_service_operation_042'
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/'sql'/name).read_text(encoding='utf-8'))
    finally:cursor.close()
def upgrade():_execute('r2_restaurant_menu_fulfillment_up.sql')
def downgrade():_execute('r2_restaurant_menu_fulfillment_down.sql')
