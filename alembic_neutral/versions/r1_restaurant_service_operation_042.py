"""Install R1 Restaurant service operation authority."""
from pathlib import Path
from alembic import op
revision='r1_restaurant_service_operation_042'
down_revision='semantic_classification_hardening_041'
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/'sql'/name).read_text(encoding='utf-8'))
    finally:cursor.close()
def upgrade():_execute('r1_restaurant_service_operation_up.sql')
def downgrade():_execute('r1_restaurant_service_operation_down.sql')
