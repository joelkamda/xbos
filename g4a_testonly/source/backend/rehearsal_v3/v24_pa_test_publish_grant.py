"""PA G4 native PostgreSQL TEST publish grant bridge.

This is strictly synthetic authorization for detached Restaurant Pack tests.
It is NOT a PC5-issued identity, issuer verification, pack entitlement in a
protected registry, or a production permission. Never treat a TEST grant as
a real deployment/Finance/merchant pack right.

Called inside the same PostgreSQL transaction as TEST product publication;
row locks serialize grant revocation and source writes.
"""
from __future__ import annotations
from datetime import datetime,timezone
from uuid import UUID
from fastapi import HTTPException

GRADE="SYNTHETIC_PG17_PERMISSION_NOT_GENUINE_PC5"
PERMISSION="restaurant.product.publish.test"

def deny(reason):
    raise HTTPException(status_code=403,detail=reason)

def require_native_test_publish_grant(c, actor, tenant_id, branch_id):
    """Fail closed unless a scoped, current DB-grant exists for session actor.

    No client-body role, token grade, or issuer assertion becomes publication
    authority. Prior FastAPI auth validates the signed rehearsal session.
    """
    if not isinstance(actor,dict) or type(tenant_id) is not int or type(branch_id) is not int:
        deny("PA_TEST_PRINCIPAL_OR_SCOPE_INVALID")
    who=actor.get("username")
    sid=actor.get("sid")
    if type(who) is not str or not who or type(sid) is not UUID:
        deny("PA_TEST_PRINCIPAL_OR_SCOPE_INVALID")
    if (tenant_id,branch_id)!=(920002,1):
        deny("PA_TEST_SCOPE_NOT_ADMITTED")
    now=datetime.now(timezone.utc)
    c.execute("""SELECT username,expires_at,revoked_at FROM v3r_sessions
                 WHERE id=%s FOR SHARE""",(sid,))
    session=c.fetchone()
    if (not session or session["username"]!=who or
        session["revoked_at"] is not None or session["expires_at"]<=now):
        deny("PA_TEST_SESSION_REVOKED_OR_EXPIRED")
    c.execute("""SELECT enabled,minimum_issuer_epoch FROM v24_pa_test_publish_policy
                 WHERE tenant_id=%s AND branch_id=%s FOR SHARE""",(tenant_id,branch_id))
    policy=c.fetchone()
    if not policy or policy["enabled"] is not True:
        deny("PA_TEST_SCOPE_DISABLED")
    c.execute("""SELECT issuer_epoch,valid_from,valid_until,revoked_at,grade
                 FROM v24_pa_test_publish_grants
                 WHERE tenant_id=%s AND branch_id=%s
                   AND actor_ref=%s AND permission=%s FOR SHARE""",
              (tenant_id,branch_id,who,PERMISSION))
    grant=c.fetchone()
    if not grant:deny("PA_TEST_ENTITLEMENT_ABSENT")
    if grant["grade"]!=GRADE:deny("PA_TEST_GRANT_PROVENANCE_DENIED")
    if grant["revoked_at"] is not None:deny("PA_TEST_GRANT_REVOKED")
    if not grant["valid_from"]<=now<grant["valid_until"]:
        deny("PA_TEST_GRANT_EXPIRED_OR_NOT_YET_EFFECTIVE")
    if grant["issuer_epoch"]<policy["minimum_issuer_epoch"]:
        deny("PA_TEST_ISSUER_EPOCH_STALE")
    return {
        "publishGrade":"NATIVE_TEST_ONLY",
        "sourceGrade":GRADE,
        "realPc5Authenticated":False,
        "realEntitlementVerified":False,
        "productionPublication":False,
    }

def require_genuine_pc5_for_operational_publish(*_args, **_kwargs):
    """Explicit non-bypassable HOLD until trusted issuer/provider is integrated."""
    deny("PA_GENUINE_PC5_ISSUER_NOT_ADMITTED")
