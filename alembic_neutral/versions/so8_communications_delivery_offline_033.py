"""Install neutral SO8 communications, delivery, integration, and offline authority."""
from pathlib import Path
from alembic import op
revision="so8_communications_delivery_offline_033"
down_revision="so7_documents_files_evidence_search_032"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("so8_communications_delivery_offline_up.sql")
def downgrade():_execute("so8_communications_delivery_offline_down.sql")
