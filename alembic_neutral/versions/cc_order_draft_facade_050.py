"""Materialize private Customer Channel draft/order facade persistence."""

from pathlib import Path

from alembic import op

revision = "cc_order_draft_facade_050"
down_revision = "cc_catalog_binding_price_code_case_049"
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
    _execute("cc_order_draft_facade_050_up.sql")


def downgrade() -> None:
    _execute("cc_order_draft_facade_050_down.sql")
