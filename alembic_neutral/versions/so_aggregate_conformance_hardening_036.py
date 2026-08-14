"""Harden Shared Operations aggregate tenant-scoped idempotency conformance."""
from pathlib import Path
from alembic import op

revision="so_aggregate_conformance_hardening_036"
down_revision="so10_scheduling_reservations_service_execution_035"
branch_labels=None
depends_on=None

def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:
        cursor.close()

def upgrade():
    _execute("so_aggregate_conformance_hardening_up.sql")

def downgrade():
    _execute("so_aggregate_conformance_hardening_down.sql")
