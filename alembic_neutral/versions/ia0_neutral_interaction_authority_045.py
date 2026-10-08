"""Install IA0 neutral interaction persistence foundation."""

from pathlib import Path

from alembic import op

revision = "ia0_neutral_interaction_authority_045"
down_revision = "r63_legacy_inventory_writer_compat_044"
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
    _execute("ia0_neutral_interaction_authority_up.sql")


def downgrade() -> None:
    _execute("ia0_neutral_interaction_authority_down.sql")
