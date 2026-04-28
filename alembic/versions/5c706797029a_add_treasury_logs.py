"""add treasury logs

Revision ID: 5c706797029a
Revises: 577f5fc9b121
Create Date: 2026-03-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "5c706797029a"
down_revision: Union[str, Sequence[str], None] = "577f5fc9b121"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade() -> None:
    """
    Create Treasury Logs table.

    This table acts as the immutable financial event ledger
    for XBOS accounting and reconciliation.
    """

    op.create_table(
        "treasury_logs",

        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "branch_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "event_type",
            sa.String(length=64),
            nullable=False,
            comment="SALE_REVENUE_GROSS | PAYMENT_RECEIVED | DEBT_CREATED | DISCOUNT_APPLIED | COMPLIMENTARY_APPLIED"
        ),

        sa.Column(
            "sale_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "payment_attempt_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "amount",
            sa.Numeric(12, 2),
            nullable=False,
        ),

        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="XAF"
        ),

        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=True,
            comment="cash | mtn | orange | wallet | card | xafpay"
        ),

        sa.Column(
            "meta",
            sa.JSON(),
            nullable=True,
            comment="additional event metadata"
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_treasury_logs_tenant_created",
        "treasury_logs",
        ["tenant_id", "created_at"],
    )

    op.create_index(
        "ix_treasury_logs_sale",
        "treasury_logs",
        ["sale_id"],
    )

    op.create_index(
        "ix_treasury_logs_attempt",
        "treasury_logs",
        ["payment_attempt_id"],
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade() -> None:
    """Drop Treasury Logs table."""

    op.drop_index("ix_treasury_logs_attempt", table_name="treasury_logs")
    op.drop_index("ix_treasury_logs_sale", table_name="treasury_logs")
    op.drop_index("ix_treasury_logs_tenant_created", table_name="treasury_logs")

    op.drop_table("treasury_logs")