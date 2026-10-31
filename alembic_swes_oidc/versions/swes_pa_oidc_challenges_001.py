"""TEST-only OIDC challenge storage; independent from neutral WND ancestry."""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "swes_pa_oidc_challenges_001"
down_revision = None
branch_labels = None
depends_on = None

SOURCE = Path(__file__).resolve().parents[2] / "platform_admin"


def _execute(name: str) -> None:
    # Reuse PA R7 exact add and R10 guarded rollback; no second SQL authority.
    sql = (SOURCE / name).read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    _execute("swes_google_oidc_challenges_r7.sql")


def downgrade() -> None:
    # R10 SQL refuses downgrade while any challenge exists.
    _execute("swes_google_oidc_challenges_r10_down.sql")
