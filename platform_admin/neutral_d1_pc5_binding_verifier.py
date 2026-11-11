"""D1 fail-closed *source-only* browser-to-PC5 binding verifier.

This is a pure decision boundary; it is NOT installed into FastAPI and creates
no authentication/session rows. Production use requires independently admitted
SQL readers and a migration for the durable server-owned binding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from core.platform.security_authority import ActorType, Lifecycle, SessionContext
from platform_admin.neutral_d1_read_router import BoundPC5Principal


class PC5BindingDenied(ValueError):
    """No verified PC5 browser-session linkage exists."""


@dataclass(frozen=True)
class VerifiedBrowserSession:
    """Returned only by an independently authenticated DB-backed browser reader."""
    session_id: UUID
    user_id: int
    tenant_id: int
    branch_id: int
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PersistedPC5BrowserLink:
    """Read-only projection of a durable server-side link, never browser input."""
    browser_session_id: UUID
    user_id: int
    tenant_id: int
    branch_id: int
    pc5_session_id: UUID
    pc5_identity_id: int
    expires_at: datetime
    revoked_at: datetime | None = None


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PC5BindingDenied("TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def verify_browser_to_pc5_binding(
    bearer: str,
    *,
    verify_browser_access: Callable[[str], VerifiedBrowserSession],
    read_server_owned_link: Callable[[UUID], PersistedPC5BrowserLink | None],
    read_pc5_session: Callable[[UUID], SessionContext | None],
    read_pc5_identity_status: Callable[[int], Lifecycle | None],
    clock: Callable[[], datetime],
) -> BoundPC5Principal:
    """All authority comes from trusted readers; never from token claims alone.

    The browser reader MUST verify signature, expiry, revocation and current
    database user/tenant/branch. The link reader MUST query a durable mapping
    owned by the server, and never use browser-supplied PC5 session identifiers.
    PC5 is separately authoritative for session, identity and membership/role
    authorization on the later neutral read endpoint.
    """
    if not isinstance(bearer, str) or not bearer.strip():
        raise PC5BindingDenied("BEARER_REQUIRED")
    try:
        now = _utc(clock())
        browser = verify_browser_access(bearer)
        if not isinstance(browser, VerifiedBrowserSession):
            raise PC5BindingDenied("BROWSER_VERIFIER_NOT_TRUSTED")
        if not isinstance(browser.session_id, UUID) or browser.user_id <= 0:
            raise PC5BindingDenied("BROWSER_CONTEXT_INVALID")
        if browser.tenant_id <= 0 or browser.branch_id <= 0:
            raise PC5BindingDenied("BROWSER_SCOPE_INVALID")
        if browser.revoked_at is not None or _utc(browser.expires_at) <= now:
            raise PC5BindingDenied("BROWSER_SESSION_INACTIVE")
        link = read_server_owned_link(browser.session_id)
        if not isinstance(link, PersistedPC5BrowserLink):
            raise PC5BindingDenied("SERVER_OWNED_LINK_ABSENT")
        if (link.browser_session_id != browser.session_id
            or link.user_id != browser.user_id
            or link.tenant_id != browser.tenant_id
            or link.branch_id != browser.branch_id):
            raise PC5BindingDenied("SERVER_OWNED_LINK_CONTEXT_MISMATCH")
        if link.revoked_at is not None or _utc(link.expires_at) <= now:
            raise PC5BindingDenied("SERVER_OWNED_LINK_INACTIVE")
        if not isinstance(link.pc5_session_id, UUID) or link.pc5_identity_id <= 0:
            raise PC5BindingDenied("LINK_PC5_IDENTITY_INVALID")
        session = read_pc5_session(link.pc5_session_id)
        if not isinstance(session, SessionContext):
            raise PC5BindingDenied("PC5_SESSION_MISSING")
        if (session.public_id != link.pc5_session_id
            or session.identity_id != link.pc5_identity_id
            or session.tenant_id != browser.tenant_id
            or session.actor_type is not ActorType.HUMAN):
            raise PC5BindingDenied("PC5_SESSION_CONTEXT_MISMATCH")
        if session.revoked_at is not None or _utc(session.expires_at) <= now:
            raise PC5BindingDenied("PC5_SESSION_INACTIVE")
        if _utc(session.authenticated_at) > now:
            raise PC5BindingDenied("PC5_SESSION_FROM_FUTURE")
        if read_pc5_identity_status(session.identity_id) is not Lifecycle.ACTIVE:
            raise PC5BindingDenied("PC5_IDENTITY_NOT_ACTIVE")
        return BoundPC5Principal(
            session_id=session.public_id,
            tenant_id=browser.tenant_id,
            branch_id=browser.branch_id,
        )
    except PC5BindingDenied:
        raise
    except Exception as exc:
        raise PC5BindingDenied("TRUSTED_AUTHORITY_UNAVAILABLE") from exc

def verify_local_delegated_read(
    principal: BoundPC5Principal,
    *,
    scope,
    read_delegation,
    read_role,
    read_membership_active,
    read_locally_revoked,
    read_device_verified,
    read_signed_lease,
    clock,
) -> BoundPC5Principal:
    """Additional local-PC5/PC4 server-owned read admission, source-only.

    All readers MUST resolve live local SQL + preissued signed issuer proofs.
    No browser-provided role, node, lease, or local session ID is accepted.
    Original D1 get_verified_pc5_binding remains 503 until independently
    commissioned real browser->PC5 and tenant production readers.
    """
    from core.platform.security_authority.local_issuer import (
        permit_local_session, LocalAuthorityDenied,
    )
    from core.platform.operating_context.signed_entitlement_lease import (
        require_entitlement, LeaseDenied,
    )
    if not isinstance(principal, BoundPC5Principal):
        raise PC5BindingDenied("LOCAL_PC5_PRINCIPAL_MISSING")
    if (getattr(scope, "tenant_id", None) != principal.tenant_id or
            getattr(scope, "branch_id", None) != principal.branch_id):
        raise PC5BindingDenied("LOCAL_SCOPE_TENANT_BRANCH_DENIED")
    try:
        timestamp = clock()
        role = read_role(principal.session_id)
        delegation = read_delegation(principal.session_id)
        lease = read_signed_lease(principal.tenant_id)
        permit_local_session(
            scope, delegation, role, timestamp,
            active_membership=read_membership_active(principal.session_id),
            local_revoked=read_locally_revoked(principal.session_id),
            device_verified=read_device_verified(principal.session_id),
        )
        require_entitlement(
            lease, principal.tenant_id, "neutral_read", timestamp,
        )
    except (LocalAuthorityDenied, LeaseDenied) as exc:
        raise PC5BindingDenied("LOCAL_SIGNED_AUTHORITY_DENIED") from exc
    except Exception as exc:
        raise PC5BindingDenied("LOCAL_AUTHORITY_READBACK_UNAVAILABLE") from exc
    return principal
