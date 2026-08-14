"""Install neutral SO7 document, file-version, evidence, and search authority."""
from pathlib import Path
from alembic import op
revision="so7_documents_files_evidence_search_032"
down_revision="so6_workflows_tasks_operational_approvals_031"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so7_documents_files_evidence_search_up.sql")
def downgrade():_execute("so7_documents_files_evidence_search_down.sql")
