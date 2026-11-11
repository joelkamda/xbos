"""No hosted DB access or migration mutation. Validate D1 migration/read contracts."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from alembic.script import ScriptDirectory
from alembic.config import Config
from sqlalchemy.dialects import postgresql

from platform_admin.neutral_d1_db_readers import D1SQLAuthorityReaders, LINK_READ_SQL
from core.platform.security_authority import Lifecycle

ROOT = Path(__file__).resolve().parents[2]


def test_proposed_d1_migration_is_outside_frozen_pc0_inventory():
    import ast
    cfg = Config(str(ROOT / "alembic_neutral.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic_neutral"))
    scripts = ScriptDirectory.from_config(cfg)
    # Exact PC0 registered inventory remains unchanged. Only the qualified
    # migration proposal has 052; it is not an installed migration head.
    assert scripts.get_heads() == ["browser_session_v1_051"]
    candidate = ROOT / "d1_migration_proposals" / "d1_pc5_browser_link_052.py"
    assert candidate.is_file()
    tree = ast.parse(candidate.read_text(encoding="utf-8"))
    declarations = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"revision", "down_revision"}):
            declarations[node.targets[0].id] = ast.literal_eval(node.value)
    assert declarations == {
        "revision": "d1_pc5_browser_link_052",
        "down_revision": "browser_session_v1_051",
    }
    assert not (ROOT / "alembic_neutral/versions/d1_pc5_browser_link_052.py").exists()


def test_sql_reader_requires_server_owned_legacy_pc5_identity_mapping():
    compiled = str(LINK_READ_SQL.compile(dialect=postgresql.dialect()))
    assert "identity_compatibility_mappings" in compiled
    assert "xbos_browser_user" in compiled
    assert "m.identity_id = link.pc5_identity_id" in compiled
    assert "b.tenant_id = link.tenant_id" in compiled
    assert "b.branch_id = link.branch_id" in compiled
    assert "link.revoked_at IS NULL" in compiled
    assert "b.revoked_at IS NULL" in compiled
    assert ":sid" in str(LINK_READ_SQL)


class FakeResult:
    def __init__(self, row=None, status=None):
        self.row = row
        self.status = status
    def mappings(self):
        return self
    def one_or_none(self):
        return self.row
    def scalar_one_or_none(self):
        return self.status


class FakeDB:
    def __init__(self, row=None, status="active"):
        self.row = row
        self.status = status
        self.calls = []
    def execute(self, statement, values):
        self.calls.append((str(statement), values))
        if "identity_compatibility_mappings" in str(statement):
            return FakeResult(row=self.row)
        return FakeResult(status=self.status)


def test_reader_returns_absent_link_as_none_not_synthetic_success():
    db = FakeDB()
    assert D1SQLAuthorityReaders(db).read_server_owned_link(uuid4()) is None
    assert db.calls and db.calls[0][1].keys() == {"sid"}


def test_reader_maps_only_durable_sql_row():
    sid = uuid4()
    pc5 = uuid4()
    dt = datetime(2026, 11, 11, tzinfo=timezone.utc)
    row = dict(browser_session_id=str(sid), user_id=9, tenant_id=2, branch_id=3,
               pc5_session_id=str(pc5), pc5_identity_id=71,
               expires_at=dt + timedelta(minutes=5), revoked_at=None)
    db = FakeDB(row=row)
    result = D1SQLAuthorityReaders(db).read_server_owned_link(sid)
    assert result.pc5_session_id == pc5
    assert result.browser_session_id == sid
    assert result.user_id == 9 and result.tenant_id == 2 and result.branch_id == 3


def test_reader_identity_status_fails_closed_on_missing():
    db = FakeDB(status=None)
    assert D1SQLAuthorityReaders(db).read_pc5_identity_status(71) is None


def test_reader_identity_status_active_or_revoked():
    assert D1SQLAuthorityReaders(FakeDB(status="active")).read_pc5_identity_status(71) is Lifecycle.ACTIVE
    assert D1SQLAuthorityReaders(FakeDB(status="revoked")).read_pc5_identity_status(71) is Lifecycle.REVOKED


def test_bad_identity_parameter_denied():
    import pytest
    with pytest.raises(TypeError):
        D1SQLAuthorityReaders(FakeDB()).read_pc5_identity_status(0)
    with pytest.raises(TypeError):
        D1SQLAuthorityReaders(FakeDB()).read_server_owned_link("client-supplied-uuid")
