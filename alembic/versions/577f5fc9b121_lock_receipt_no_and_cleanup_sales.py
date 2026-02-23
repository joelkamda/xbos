"""lock_receipt_no_and_cleanup_sales

revision = "577f5fc9b121"
down_revision = "fff36dab3483"
branch_labels = None
depends_on = None

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "577f5fc9b121"
down_revision = "fff36dab3483"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------
    # SALES: add receipt_no
    # -------------------------------------------------
    op.add_column(
        "sales",
        sa.Column(
            "receipt_no",
            sa.String(length=32),
            nullable=False,
            comment="Human-readable receipt / bill number",
        ),
    )

    # -------------------------------------------------
    # SALES: drop deprecated payment_summary
    # -------------------------------------------------
    op.drop_column("sales", "payment_summary")

    # -------------------------------------------------
    # SALES: receipt uniqueness (tenant + branch)
    # -------------------------------------------------
    op.create_index(
        "ux_sales_receipt_no",
        "sales",
        ["tenant_id", "branch_id", "receipt_no"],
        unique=True,
    )

    # -------------------------------------------------
    # SALE_ITEMS: quantity must be positive
    # -------------------------------------------------
    op.create_check_constraint(
        "ck_sale_item_quantity_positive",
        "sale_items",
        "quantity > 0",
    )


def downgrade() -> None:
    # -------------------------------------------------
    # SALE_ITEMS
    # -------------------------------------------------
    op.drop_constraint(
        "ck_sale_item_quantity_positive",
        "sale_items",
        type_="check",
    )

    # -------------------------------------------------
    # SALES
    # -------------------------------------------------
    op.drop_index("ux_sales_receipt_no", table_name="sales")

    op.add_column(
        "sales",
        sa.Column(
            "payment_summary",
            sa.JSON(),
            nullable=True,
        ),
    )

    op.drop_column("sales", "receipt_no")
