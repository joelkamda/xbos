"""Install neutral SO9 reporting, read-model, metric, and report-automation authority."""
from pathlib import Path
from alembic import op
revision="so9_reporting_read_models_automation_034"
down_revision="so8_communications_delivery_offline_033"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so9_reporting_read_models_automation_up.sql")
def downgrade():_execute("so9_reporting_read_models_automation_down.sql")
