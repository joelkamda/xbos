"""Adopt legacy Atomic Units and install neutral SO1 catalog, offer and pricing authority."""
from pathlib import Path
from alembic import op

revision = "so1_atomic_catalog_offer_pricing_026"
down_revision = "pc5_identity_policy_audit_025"
branch_labels = None
depends_on = None


def _execute(name):
    cursor = op.get_bind().connection.cursor()
    try: cursor.execute((Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8"))
    finally: cursor.close()


def upgrade(): _execute("so1_atomic_catalog_offer_pricing_up.sql")
def downgrade(): _execute("so1_atomic_catalog_offer_pricing_down.sql")
