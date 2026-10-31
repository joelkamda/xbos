"""Single-human initial PC5 enrollment behind independently approved Google subject pin.

This is a source-qualified, transaction-bound executor, NOT a live endpoint.
Only invoke synchronously after a genuine verified Google OIDC callback, in an
already authenticated/authorized, exact TEST database transaction. Google OIDC
proof provides assurance 1 only; high-risk PA permission requires level 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from core.platform.security_authority import (
    ActorType, AuditEnvelope, AuthorizationRequest, Decision,
    PermissionDefinition, RoleAssignment, ScopeType, SecurityAuthority,
    SQLSecurityRepository, StructuralScope,
)
from platform_admin.swes_google_oidc_r7 import (
    ISSUER, OIDCConfig, OIDCHold, TENANT_ID, VerifiedIdentity,
    owner_binding_gate,
)

ROLE = "swes_wnd_pa_admin"
PERMISSION = "pa.merchant.admin"


@dataclass(frozen=True)
class OwnerPC5Enrollment:
    identity_public_id: str
    session_public_id: str
    tenant_id: int
    permission_code: str
    authorization_decision: str
    required_assurance: int
    audit_public_id: str
    operational_admission: bool = False


def enroll_verified_ceo(*, db_session, identity: VerifiedIdentity, config: OIDCConfig,
                        ceo_approval_registered: bool, at: datetime) -> OwnerPC5Enrollment:
    if at.tzinfo is None or identity.authenticated_at.tzinfo is None:
        raise OIDCHold("HOLD_AUTHENTICATED_CLOCK")
    owner_binding_gate(identity, config, ceo_approval_registered=ceo_approval_registered)
    if (
        identity.assurance_level != 1
        or identity.authenticated_at > at + timedelta(seconds=30)
        or at - identity.authenticated_at > timedelta(minutes=5)
    ):
        raise OIDCHold("HOLD_GOOGLE_AUTHENTICATION_AGE_OR_ASSURANCE")
    # Required: caller owns an active single DB transaction; do NOT autocreate
    # a session/role outside the verified OIDC callback and trusted admission.
    name = db_session.execute(text("SELECT current_database()")).scalar_one()
    if name != "wnd_xafpay_demo_austin_db":
        raise OIDCHold("HOLD_WRONG_DATABASE")
    tenant = db_session.execute(text("""
        SELECT id FROM public.tenants WHERE id=:t AND
        code='SWES_WND_AUSTIN_TEST' AND lifecycle_state='active' FOR UPDATE
    """), {"t": TENANT_ID}).scalar_one_or_none()
    if tenant != TENANT_ID:
        raise OIDCHold("HOLD_WRONG_TENANT")
    # First-owner only. The lock serializes concurrent callbacks; a second
    # enrollment must be handled as a separate authenticated continuation.
    existing = db_session.execute(text("""
        SELECT
          (SELECT count(*) FROM public.identity_memberships WHERE tenant_id=:t) AS memberships,
          (SELECT count(*) FROM public.authorization_roles WHERE tenant_id=:t) AS roles,
          (SELECT count(*) FROM public.authentication_sessions WHERE tenant_id=:t) AS sessions
    """), {"t": TENANT_ID}).one()
    if any(int(value) != 0 for value in existing):
        raise OIDCHold("HOLD_FIRST_OPERATOR_ALREADY_ESTABLISHED")
    authority = SecurityAuthority(SQLSecurityRepository(db_session))
    actor = authority.create_identity(
        command_key="swes:r7:pc5:ceo:google:identity",
        login_name="google-oidc:" + identity.subject_sha256,
    )
    authority.add_membership(
        command_key="swes:r7:pc5:ceo:membership", identity_id=actor.id,
        tenant_id=TENANT_ID, valid_from=at
    )
    # This permission is narrowly tenant-scoped, NOT platform-wide,
    # and requires step-up assurance 2 for authorization.
    definition = PermissionDefinition(
        PERMISSION, "pa", "merchant", "admin", "high",
        (ScopeType.TENANT,), 2
    )
    if authority.repository.permission(PERMISSION) is None:
        authority.register_permission(
            command_key="swes:r7:pc5:ceo:permission", definition=definition
        )
    else:
        present = authority.repository.permission(PERMISSION)
        if present != definition:
            raise OIDCHold("HOLD_EXISTING_PERMISSION_POLICY_CONFLICT")
    authority.create_role(
        command_key="swes:r7:pc5:ceo:role", role_code=ROLE,
        tenant_id=TENANT_ID, permissions=(PERMISSION,)
    )
    scope = StructuralScope(ScopeType.TENANT, TENANT_ID)
    authority.assign_role(
        command_key="swes:r7:pc5:ceo:assignment",
        assignment=RoleAssignment(actor.id, TENANT_ID, ROLE, scope, at)
    )
    session = authority.create_session(
        command_key="swes:r7:pc5:ceo:session", identity_id=actor.id,
        tenant_id=TENANT_ID, actor_type=ActorType.HUMAN,
        assurance_level=1, authenticated_at=identity.authenticated_at,
        expires_at=at + timedelta(minutes=10),
    )
    decision = authority.authorize(AuthorizationRequest(
        session.public_id, PERMISSION, TENANT_ID, scope,
        "merchant", "wnd-austin-test", at,
        correlation_id="swes-r7-ceo-initial-oidc",
    ))
    if decision.decision is not Decision.REQUIRE_STEP_UP:
        # No unsupported MFA claim can promote the first Google login to
        # PA admin. Only an independently verified step-up may do so later.
        raise OIDCHold("HOLD_UNEXPECTED_FIRST_LOGIN_ADMIN_DECISION")
    audit_id = uuid4()
    authority.append_audit(AuditEnvelope(
        audit_id, TENANT_ID, actor.id, ActorType.HUMAN,
        "pa.owner.initial_enrollment", "pc5_identity", str(actor.public_id),
        "step_up_required", at, "pa", "swes-r7-ceo-initial-oidc",
        session.public_id, scope=scope,
        metadata={"issuer":"google", "assurance_level":1,
                  "owner_approval_present":True, "tenant":TENANT_ID},
    ))
    return OwnerPC5Enrollment(
        str(actor.public_id), str(session.public_id), TENANT_ID,
        PERMISSION, decision.decision.value, decision.required_assurance,
        str(audit_id),
    )
