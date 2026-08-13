"""Install canonical PC5 identity, policy, approval, and audit authority."""
from pathlib import Path
from alembic import op

revision = "pc5_identity_policy_audit_025"
down_revision = "pc4_operating_context_024"
branch_labels = None
depends_on = None


def _execute(name):
    cursor = op.get_bind().connection.cursor()
    try: cursor.execute((Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8"))
    finally: cursor.close()


def upgrade(): _execute("pc5_identity_policy_audit_up.sql")
def downgrade(): _execute("pc5_identity_policy_audit_down.sql")
