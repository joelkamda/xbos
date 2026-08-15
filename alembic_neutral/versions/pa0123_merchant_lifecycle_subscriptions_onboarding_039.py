"""Install PA0-PA3 merchant lifecycle, commercial administration, usage and onboarding authority."""
from pathlib import Path
from alembic import op
revision="pa0123_merchant_lifecycle_subscriptions_onboarding_039"
down_revision="pk456_pack_conformance_templates_038"
branch_labels=None
depends_on=None

def _execute(name):
    cursor=op.get_bind().connection.cursor()
    try: cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally: cursor.close()

def upgrade(): _execute("pa0123_merchant_lifecycle_subscriptions_onboarding_up.sql")
def downgrade(): _execute("pa0123_merchant_lifecycle_subscriptions_onboarding_down.sql")
