"""Reconstruct the approved XBOS source-state schema without row data.

Revision ID: m12_source_state_001
Revises: None
Create Date: 2026-08-06
"""

from hashlib import sha256
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "m12_source_state_001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = ("m12_reconstruction_candidate",)
depends_on: Union[str, Sequence[str], None] = None

BASELINE_SQL_PATH = (
    Path(__file__).resolve().parents[1] / "sql" / "source_state_baseline.sql"
)
BASELINE_SQL_SHA256 = (
    "6d28e558e7292bd018cdb27c849725b899eabf834540b9f0512a7c6b64d44faf"
)


def _verified_baseline_sql() -> str:
    sql = BASELINE_SQL_PATH.read_text(encoding="utf-8")
    actual_hash = sha256(sql.encode("utf-8")).hexdigest()

    if actual_hash != BASELINE_SQL_SHA256:
        raise RuntimeError(
            "M1.2 source-state baseline SQL checksum mismatch: "
            f"expected {BASELINE_SQL_SHA256}, got {actual_hash}"
        )

    if "CREATE TABLE public.alembic_version" in sql:
        raise RuntimeError("Baseline SQL must not create Alembic's version table")

    if "\nCOPY " in sql or "\nINSERT INTO " in sql:
        raise RuntimeError("Baseline SQL must not contain application row data")

    return sql


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_verified_baseline_sql())


def downgrade() -> None:
    raise RuntimeError(
        "The M1.2 reconstruction baseline is forward-only; discard the "
        "disposable database instead of downgrading it"
    )
