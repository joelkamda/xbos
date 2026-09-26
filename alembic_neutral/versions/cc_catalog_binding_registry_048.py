"""Materialize Customer Channel catalog read binding registry."""

from pathlib import Path

from alembic import op

revision = "cc_catalog_binding_registry_048"
down_revision = "cch_customer_channel_checkout_authority_047"
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
    _execute("cc_catalog_binding_registry_up.sql")


def downgrade() -> None:
    _execute("cc_catalog_binding_registry_down.sql")
