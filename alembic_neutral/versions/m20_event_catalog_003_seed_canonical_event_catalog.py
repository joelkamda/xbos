"""Seed the approved canonical financial-event catalog.

Revision ID: m20_event_catalog_003
Revises: m13_financial_foundation_002
"""

from alembic import op
from sqlalchemy import text

from core.persistence.m20_event_catalog import seed_catalog, seed_identities


revision = "m20_event_catalog_003"
down_revision = "m13_financial_foundation_002"
branch_labels = None
depends_on = None


_APPROVED_EFFECTS = (
    "inflow",
    "outflow",
    "movement",
    "control_increase",
    "control_decrease",
    "control_reversal",
    "commercial",
    "account_adjustment",
    "none",
)


def _replace_effect_constraint(effects):
    quoted = ",".join(f"'{effect}'" for effect in effects)
    op.execute(
        "ALTER TABLE public.financial_event_type_versions "
        "DROP CONSTRAINT ck_financial_event_type_versions_recon_effect"
    )
    op.execute(
        "ALTER TABLE public.financial_event_type_versions "
        "ADD CONSTRAINT ck_financial_event_type_versions_recon_effect "
        f"CHECK (reconciliation_effect IN ({quoted}))"
    )


def upgrade() -> None:
    # M0's executable contract supersedes the older coarse empty-table check.
    _replace_effect_constraint(_APPROVED_EFFECTS)
    inserted = seed_catalog(op.get_bind())
    if inserted != 20:
        raise RuntimeError(f"Expected to seed 20 catalog rows; inserted {inserted}")


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        "ALTER TABLE public.financial_event_type_versions "
        "DISABLE TRIGGER tr_financial_event_types_immutable"
    )
    delete_row = text(
        """
        DELETE FROM public.financial_event_type_versions
        WHERE event_type_code = :event_type_code AND event_version = :event_version
        """
    )
    for event_type_code, event_version in seed_identities():
        bind.execute(
            delete_row,
            {"event_type_code": event_type_code, "event_version": event_version},
        )
    op.execute(
        "ALTER TABLE public.financial_event_type_versions "
        "ENABLE TRIGGER tr_financial_event_types_immutable"
    )
    _replace_effect_constraint(
        ("inflow", "outflow", "movement", "control", "commercial", "none")
    )
