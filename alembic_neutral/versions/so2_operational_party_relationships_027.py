"""Install neutral SO2 operational Party relationship authority."""
from pathlib import Path
from alembic import op

revision = "so2_operational_party_relationships_027"
down_revision = "so1_atomic_catalog_offer_pricing_026"
branch_labels = None
depends_on = None


def _execute(name):
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8"))
    finally:
        cursor.close()


def upgrade():
    _execute("so2_operational_party_relationships_up.sql")


def downgrade():
    _execute("so2_operational_party_relationships_down.sql")
