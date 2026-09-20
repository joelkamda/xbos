"""Add lifecycle state to R1 restaurant order lines."""

from pathlib import Path

from alembic import op

revision = "r1_restaurant_order_line_lifecycle_046"
down_revision = "ia0_neutral_interaction_authority_045"
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
    _execute("r1_restaurant_order_line_lifecycle_up.sql")


def downgrade() -> None:
    _execute("r1_restaurant_order_line_lifecycle_down.sql")
