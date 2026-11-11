"""D1 browser-to-PC5 server-owned linking (source-only until approved recovery).

No automatic grant to application roles or network/service configuration.
Requires verified browser_session_v1_051 and earlier PC5 identity schema.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1_pc5_browser_link_052"
down_revision = "browser_session_v1_051"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "d1_pc5_browser_links",
        sa.Column("browser_session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("pc5_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pc5_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("browser_session_id", name="pk_d1_pc5_browser_links"),
        sa.ForeignKeyConstraint(["browser_session_id"], ["xbos_browser_sessions.session_id"],
                                name="fk_d1_pc5_link_browser", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_d1_pc5_link_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pc5_session_id"], ["authentication_sessions.public_id"],
                                name="fk_d1_pc5_link_session", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pc5_identity_id"], ["identities.id"],
                                name="fk_d1_pc5_link_identity", ondelete="RESTRICT"),
        sa.CheckConstraint("expires_at > created_at", name="ck_d1_pc5_link_period"),
        sa.CheckConstraint("user_id > 0 AND tenant_id > 0 AND branch_id > 0",
                           name="ck_d1_pc5_link_scope"),
        sa.UniqueConstraint("pc5_session_id", name="uq_d1_pc5_session_one_browser"),
        schema="public",
    )
    op.create_index("ix_d1_pc5_link_scope", "d1_pc5_browser_links",
                    ["tenant_id", "branch_id"], schema="public")
    op.execute("REVOKE ALL ON TABLE public.d1_pc5_browser_links FROM PUBLIC")
    # No application SELECT/INSERT/UPDATE/DELETE grants.
    # Add grants only after a distinct least-privilege role admission.


def downgrade():
    # Deliberately fail if the link table contains custody records. Data must
    # first be independently backed up and reconciled; no destructive reset.
    op.execute("""
      DO $$
      BEGIN
        IF EXISTS (SELECT 1 FROM public.d1_pc5_browser_links LIMIT 1) THEN
          RAISE EXCEPTION 'D1_LINK_HAS_CUSTODY_ROWS_ROLLBACK_DENIED';
        END IF;
      END $$;
    """)
    op.drop_index("ix_d1_pc5_link_scope", table_name="d1_pc5_browser_links",
                  schema="public")
    op.drop_table("d1_pc5_browser_links", schema="public")
