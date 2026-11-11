"""Unit source gate for server-only D1 issuance; not live PG admission."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy.dialects import postgresql
from core.platform.security_authority import ActorType, Lifecycle, SessionContext
from platform_admin.neutral_d1_pc5_binding_verifier import (
    PC5BindingDenied, VerifiedBrowserSession
)
from platform_admin.neutral_d1_link_custody import (
    ISSUE_SQL, REVOKE_SQL, issue_server_owned_link, revoke_server_owned_link
)
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
BS = uuid4()
PC = uuid4()


def records():
    b = VerifiedBrowserSession(BS, 42, 7, 11, NOW + timedelta(minutes=15))
    p = SessionContext(12, PC, 1002, 7, ActorType.HUMAN, 2,
                       NOW-timedelta(minutes=5), NOW+timedelta(minutes=10))
    return b,p


class FakeSQL:
    def __init__(self, answer=BS, error=None):
        self.answer=answer
        self.error=error
        self.calls=[]
    def execute(self, sql, values):
        self.calls.append((sql, values))
        if self.error:
            raise self.error
        class R:
            def __init__(self, value): self.value=value
            def scalar_one_or_none(self): return self.value
        return R(self.answer)


def test_issuance_requires_independent_complete_records():
    b,p=records()
    db=FakeSQL()
    assert issue_server_owned_link(db,browser=b,pc5=p,identity_status=Lifecycle.ACTIVE,
                                   now=NOW,expires_at=NOW+timedelta(minutes=6))==BS
    assert db.calls[0][0] is ISSUE_SQL
    assert db.calls[0][1]["identity"]==1002
    assert db.calls[0][1]["tenant"]==7
    assert "password" not in db.calls[0][1]
    assert not hasattr(db,"commit")


@pytest.mark.parametrize("change", [
    lambda b,p:(replace(b, tenant_id=8),p),
    lambda b,p:(replace(b, revoked_at=NOW),p),
    lambda b,p:(replace(b, expires_at=NOW),p),
    lambda b,p:(b,replace(p, revoked_at=NOW)),
    lambda b,p:(b,replace(p, expires_at=NOW)),
    lambda b,p:(b,replace(p, actor_type=ActorType.SERVICE)),
    lambda b,p:(b,replace(p, authenticated_at=NOW+timedelta(seconds=2))),
])
def test_issuance_denies_mismatched_or_inactive_authority(change):
    b,p=change(*records())
    db=FakeSQL()
    with pytest.raises(PC5BindingDenied):
        issue_server_owned_link(db,browser=b,pc5=p,identity_status=Lifecycle.ACTIVE,
                                now=NOW,expires_at=NOW+timedelta(minutes=5))
    assert db.calls==[]


def test_issuance_denies_inactive_identity_and_beyond_pc5_expiry():
    b,p=records()
    for status in (Lifecycle.SUSPENDED,Lifecycle.REVOKED,None):
        with pytest.raises(PC5BindingDenied):
            issue_server_owned_link(FakeSQL(),browser=b,pc5=p,identity_status=status,
                                    now=NOW,expires_at=NOW+timedelta(minutes=5))
    with pytest.raises(PC5BindingDenied):
        issue_server_owned_link(FakeSQL(),browser=b,pc5=p,identity_status=Lifecycle.ACTIVE,
                                now=NOW,expires_at=NOW+timedelta(minutes=12))


def test_db_denial_and_missing_link_fail_closed():
    b,p=records()
    with pytest.raises(PC5BindingDenied,match="LINK_TRUST_PROOF_NOT_SATISFIED"):
        issue_server_owned_link(FakeSQL(answer=None),browser=b,pc5=p,
                                identity_status=Lifecycle.ACTIVE,now=NOW,
                                expires_at=NOW+timedelta(minutes=4))
    with pytest.raises(PC5BindingDenied,match="LINK_CUSTODY_ISSUANCE_UNAVAILABLE"):
        issue_server_owned_link(FakeSQL(error=RuntimeError("database offline")),browser=b,pc5=p,
                                identity_status=Lifecycle.ACTIVE,now=NOW,
                                expires_at=NOW+timedelta(minutes=4))


def test_exact_scoped_revoke_and_no_unbounded_update():
    b,p=records()
    db=FakeSQL()
    assert revoke_server_owned_link(db,browser=b,pc5=p,now=NOW)==BS
    assert db.calls[0][0] is REVOKE_SQL
    stmt=str(REVOKE_SQL)
    for field in ("browser_session_id", "user_id", "tenant_id", "branch_id",
                  "pc5_session_id", "pc5_identity_id", "revoked_at IS NULL"):
        assert field in stmt
    with pytest.raises(PC5BindingDenied,match="LINK_NOT_FOUND_OR_ALREADY_REVOKED"):
        revoke_server_owned_link(FakeSQL(answer=None),browser=b,pc5=p,now=NOW)


def test_sql_requires_authoritative_membership_and_locks():
    sql=str(ISSUE_SQL.compile(dialect=postgresql.dialect()))
    for fragment in ("identity_compatibility_mappings","identity_memberships",
        "member.status = 'active'", "member.invitation_state = 'accepted'",
        "s.principal_id = i.id","s.tenant_id = b.tenant_id",
        "FOR UPDATE OF b, i, s, m, member",
        "INSERT INTO public.d1_pc5_browser_links"):
        assert fragment in sql
    assert "ON CONFLICT DO UPDATE" not in sql
