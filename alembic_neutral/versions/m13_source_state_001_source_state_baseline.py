"""Adopt the approved M1.2 source-state reconstruction baseline.

Revision ID: m13_source_state_001
Revises: None
"""

import importlib.util
from pathlib import Path

from alembic import op


revision = "m13_source_state_001"
down_revision = None
branch_labels = None
depends_on = None


def _approved_m12_revision():
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "alembic_reconstruction"
        / "versions"
        / "m12_source_state_001_source_state_baseline.py"
    )
    if not path.is_file():
        raise RuntimeError(f"Approved M1.2 source-state revision is missing: {path}")
    spec = importlib.util.spec_from_file_location("xbos_approved_m12_baseline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load approved M1.2 revision: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    _approved_m12_revision().upgrade()
    # A schema-only source dump may remove the version table created by Alembic
    # before the first revision. Recreate the empty authority table so Alembic
    # can record this revision after upgrade() returns.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "The adopted source-state baseline is not destructively downgraded. "
        "Drop only a specifically named disposable rehearsal database."
    )
