"""Install PA4-PA5 support, recovery, delegated administration and health authority."""
from pathlib import Path
from alembic import op

revision="pa45_support_recovery_health_040"
down_revision="pa0123_merchant_lifecycle_subscriptions_onboarding_039"
branch_labels=None
depends_on=None


def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:
        cursor.close()


def upgrade(): _execute("pa45_support_recovery_health_up.sql")
def downgrade(): _execute("pa45_support_recovery_health_down.sql")
