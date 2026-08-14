"""Install neutral SO6 workflow, task, and operational-approval authority."""
from pathlib import Path
from alembic import op
revision="so6_workflows_tasks_operational_approvals_031"
down_revision="so5_resources_operational_assignment_030"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so6_workflows_tasks_operational_approvals_up.sql")
def downgrade():_execute("so6_workflows_tasks_operational_approvals_down.sql")
