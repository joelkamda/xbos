"""Materialize XBOS Restaurant Customer Channel checkout authority."""

from pathlib import Path

from alembic import op

revision = "cch_customer_channel_checkout_authority_047"
down_revision = "r1_restaurant_order_line_lifecycle_046"
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
    _execute("cch_customer_channel_checkout_authority_up.sql")


def downgrade() -> None:
    _execute("cch_customer_channel_checkout_authority_down.sql")
