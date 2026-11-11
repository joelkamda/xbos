"""D1 server-side linkage custody source. NOT installed on a hosted runtime.

Caller must have already independently authenticated both the browser user
and the PC5 session. Issuance only binds existing authoritative rows under a
transaction, never accepts request-supplied identities or grants PC5 roles.
No token or bearer credential is stored or logged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import text

from core.platform.security_authority import ActorType, Lifecycle, SessionContext
from platform_admin.neutral_d1_pc5_binding_verifier import (
    PC5BindingDenied, VerifiedBrowserSession
)

# This SQL is *one* atomic, checked issuance statement; PostgreSQL locks the
# matching rows with FOR UPDATE OF b,s,i,m and refuses mismatched linkage.
ISSUE_SQL = text("""
WITH verified AS (
  SELECT b.session_id AS sid
  FROM public.xbos_browser_sessions b
  JOIN public.identity_compatibility_mappings m
    ON m.source_authority = 'xbos_browser_user'
   AND m.source_record_id = b.user_id::text
   AND m.identity_id = :identity
  JOIN public.identities i ON i.id = m.identity_id
  JOIN public.authentication_sessions s
    ON s.public_id = :pc5
   AND s.principal_id = i.id
   AND s.tenant_id = b.tenant_id
   AND s.actor_type = 'human'
  JOIN public.identity_memberships member
    ON member.id = m.membership_id
   AND member.identity_id = i.id
   AND member.tenant_id = b.tenant_id
  WHERE b.session_id = :browser
    AND b.user_id = :user_id
    AND b.tenant_id = :tenant
    AND b.branch_id = :branch
    AND b.revoked_at IS NULL
    AND b.expires_at > :now
    AND i.status = 'active'
    AND member.status = 'active'
    AND member.invitation_state = 'accepted'
    AND member.revoked_at IS NULL
    AND member.valid_from <= :now
    AND (member.valid_to IS NULL OR member.valid_to > :now)
    AND s.revoked_at IS NULL
    AND s.authenticated_at <= :now
    AND s.expires_at > :now
  FOR UPDATE OF b, i, s, m, member
)
INSERT INTO public.d1_pc5_browser_links
  (browser_session_id,user_id,tenant_id,branch_id,pc5_session_id,
   pc5_identity_id,created_at,expires_at)
SELECT sid, :user_id,:tenant,:branch,:pc5,:identity,:now,:expires
FROM verified
WHERE :expires > :now
  AND :expires <= (
    SELECT b.expires_at FROM public.xbos_browser_sessions b
    WHERE b.session_id = :browser
  )
  AND :expires <= (
    SELECT s.expires_at FROM public.authentication_sessions s
    WHERE s.public_id = :pc5
  )
RETURNING browser_session_id
""")

REVOKE_SQL = text("""
UPDATE public.d1_pc5_browser_links l
   SET revoked_at = :now
 WHERE l.browser_session_id = :browser
   AND l.user_id = :user_id
   AND l.tenant_id = :tenant
   AND l.branch_id = :branch
   AND l.pc5_session_id = :pc5
   AND l.pc5_identity_id = :identity
   AND l.revoked_at IS NULL
RETURNING browser_session_id
""")


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PC5BindingDenied("TRUSTED_TIMESTAMP_REQUIRED")
    return value.astimezone(timezone.utc)


def _values(browser: VerifiedBrowserSession, session: SessionContext,
            now: datetime):
    if not isinstance(browser, VerifiedBrowserSession) or not isinstance(session, SessionContext):
        raise PC5BindingDenied("TRUSTED_AUTHORITY_RECORDS_REQUIRED")
    if (not isinstance(browser.session_id, UUID)
        or not isinstance(session.public_id, UUID)
        or browser.user_id <= 0 or browser.tenant_id <= 0 or browser.branch_id <= 0
        or session.identity_id <= 0 or session.tenant_id != browser.tenant_id
        or session.actor_type is not ActorType.HUMAN):
        raise PC5BindingDenied("BROWSER_PC5_CONTEXT_DENIED")
    now = _aware(now)
    if (browser.revoked_at is not None or session.revoked_at is not None
        or _aware(browser.expires_at) <= now or _aware(session.expires_at) <= now
        or _aware(session.authenticated_at) > now):
        raise PC5BindingDenied("BROWSER_PC5_SESSION_INACTIVE")
    return dict(browser=str(browser.session_id), user_id=browser.user_id,
                tenant=browser.tenant_id, branch=browser.branch_id,
                pc5=str(session.public_id), identity=session.identity_id,
                now=now)


def issue_server_owned_link(db, *, browser: VerifiedBrowserSession,
                            pc5: SessionContext, identity_status: Lifecycle,
                            now: datetime, expires_at: datetime):
    """Insert only after independently trusted browser + PC5 checks.

    Transaction commits are exclusively owned by the caller. Duplicate links
    fail by PRIMARY KEY / UNIQUE, rather than silently replacing their custody.
    """
    if identity_status is not Lifecycle.ACTIVE:
        raise PC5BindingDenied("PC5_IDENTITY_NOT_ACTIVE")
    values = _values(browser, pc5, now)
    expiry = _aware(expires_at)
    if expiry <= values["now"] or expiry > min(_aware(browser.expires_at),
                                               _aware(pc5.expires_at)):
        raise PC5BindingDenied("LINK_EXPIRY_OUTSIDE_BOTH_AUTHORITIES")
    values["expires"] = expiry
    try:
        inserted = db.execute(ISSUE_SQL, values).scalar_one_or_none()
    except Exception as exc:
        raise PC5BindingDenied("LINK_CUSTODY_ISSUANCE_UNAVAILABLE") from exc
    if str(inserted) != values["browser"]:
        raise PC5BindingDenied("LINK_TRUST_PROOF_NOT_SATISFIED")
    return browser.session_id


def revoke_server_owned_link(db, *, browser: VerifiedBrowserSession,
                             pc5: SessionContext, now: datetime):
    """Revoke exact previously server-verified linkage; fail closed otherwise."""
    values = _values(browser, pc5, now)
    try:
        revoked = db.execute(REVOKE_SQL, values).scalar_one_or_none()
    except Exception as exc:
        raise PC5BindingDenied("LINK_CUSTODY_REVOCATION_UNAVAILABLE") from exc
    if str(revoked) != values["browser"]:
        raise PC5BindingDenied("LINK_NOT_FOUND_OR_ALREADY_REVOKED")
    return browser.session_id
