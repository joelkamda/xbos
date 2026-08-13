"""Install canonical PC4 typed configuration and prospective operating context."""
from pathlib import Path
from alembic import op
revision="pc4_operating_context_024"
down_revision="pc3_semantic_authority_023"
branch_labels=None
depends_on=None
def _execute(name):
    # PL/pgSQL uses percent tokens such as %ROWTYPE. Execute the batch through
    # the DBAPI cursor so SQLAlchemy's pyformat parameter parser cannot treat
    # those tokens as parameters when no parameter sequence was supplied.
    cursor=op.get_bind().connection.cursor()
    try:cursor.execute((Path(__file__).resolve().parents[1]/"sql"/name).read_text(encoding="utf-8"))
    finally:cursor.close()
def upgrade():_execute("pc4_operating_context_up.sql")
def downgrade():_execute("pc4_operating_context_down.sql")
