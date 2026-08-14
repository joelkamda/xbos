"""Install neutral SO10 scheduling, reservation, capacity and service-execution authority."""
from pathlib import Path
from alembic import op
revision="so10_scheduling_reservations_service_execution_035"
down_revision="so9_reporting_read_models_automation_034"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so10_scheduling_reservations_service_execution_up.sql")
def downgrade():_execute("so10_scheduling_reservations_service_execution_down.sql")
