"""Install R6.3 legacy WND inventory-writer compatibility adapter."""
from pathlib import Path
from alembic import op

revision = "r63_legacy_inventory_writer_compat_044"
down_revision = "r2_restaurant_menu_fulfillment_043"
branch_labels = None
depends_on = None


def _execute(name: str) -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(
            (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
                encoding="utf-8"
            )
        )
    finally:
        cursor.close()


def upgrade() -> None:
    _execute("r63_legacy_inventory_writer_compat_up.sql")


def downgrade() -> None:
    _execute("r63_legacy_inventory_writer_compat_down.sql")
