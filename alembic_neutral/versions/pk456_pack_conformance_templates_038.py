"""Install PK4-PK6 pack conformance, template registry and application authority."""
from pathlib import Path
from alembic import op
revision="pk456_pack_conformance_templates_038"
down_revision="pk0123_pack_manifest_lifecycle_037"
branch_labels=None
depends_on=None

def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()

def upgrade():_execute("pk456_pack_conformance_templates_up.sql")
def downgrade():_execute("pk456_pack_conformance_templates_down.sql")
