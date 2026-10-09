"""XBOS browser-session.v1 registry only; independent of business tables."""

from alembic import op
import sqlalchemy as sa

revision = "browser_session_v1_051"
down_revision = "cc_order_draft_facade_050"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "xbos_browser_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(64), nullable=True),
        sa.Column("current_refresh_jti", sa.String(64), nullable=False),
        sa.Column("previous_refresh_jti", sa.String(64), nullable=True),
        sa.Column("previous_refresh_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_xbos_browser_sessions_user", "xbos_browser_sessions", ["user_id"])
    op.create_index("ix_xbos_browser_sessions_expiry", "xbos_browser_sessions", ["expires_at"])

def downgrade():
    op.drop_index("ix_xbos_browser_sessions_expiry", table_name="xbos_browser_sessions")
    op.drop_index("ix_xbos_browser_sessions_user", table_name="xbos_browser_sessions")
    op.drop_table("xbos_browser_sessions")
