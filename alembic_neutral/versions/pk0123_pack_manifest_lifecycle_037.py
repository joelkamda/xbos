"""Install PK0-PK3 pack manifest, lifecycle, extension and connector authority."""
from pathlib import Path
from alembic import op
revision="pk0123_pack_manifest_lifecycle_037"
down_revision="so_aggregate_conformance_hardening_036"
branch_labels=None
depends_on=None
def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("pk0123_pack_manifest_lifecycle_up.sql")
def downgrade():_execute("pk0123_pack_manifest_lifecycle_down.sql")
