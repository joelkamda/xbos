"""D1 production-reader composition source candidate, not installed in ASGI.

No DB connection is created by this module; an independently authorized
least-privilege SQLAlchemy session is supplied by the future hosted runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from platform_admin.neutral_d1_db_readers import D1SQLAuthorityReaders
from platform_admin.neutral_d1_pc5_binding_verifier import (
    PC5BindingDenied, VerifiedBrowserSession, verify_browser_to_pc5_binding,
)


def _verify_browser_session_with_authority(db, token: str, browser_auth) -> VerifiedBrowserSession:
    """Signature, JWT expiry, DB registry and actual user/branch verified twice.

    Never derive the PC5 identity or tenant authority from a request header.
    The signed claims identify only a candidate browser session to recheck.
    """
    try:
        claims = browser_auth.decode_token(token, "browser_access")
        live = browser_auth.validate_browser_access(db, token)
        sid = UUID(str(claims["sid"]))
        row = browser_auth.live_session(db, str(sid))
        if (int(claims["sub"]) != row.user_id
                or claims["tenant_id"] != row.tenant_id
                or claims["branch_id"] != row.branch_id
                or int(live["user_id"]) != row.user_id
                or int(live["tenant_id"]) != row.tenant_id
                or int(live["branch_id"]) != row.branch_id):
            raise PC5BindingDenied("BROWSER_SESSION_SCOPE_MISMATCH")
        # JWT exp has already been verified by the server's decoder. Preserve
        # the narrower expiry when the access JWT expires before the registry.
        token_exp = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        expiry = min(browser_auth.aware(row.expires_at), token_exp)
        return VerifiedBrowserSession(
            session_id=sid,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            branch_id=row.branch_id,
            expires_at=expiry,
            revoked_at=row.revoked_at,
        )
    except PC5BindingDenied:
        raise
    except Exception as exc:
        raise PC5BindingDenied("BROWSER_SESSION_UNVERIFIED") from exc


def verified_browser_session_from_sql(db, token: str) -> VerifiedBrowserSession:
    # Loading the real authority requires configured JWT_SECRET and DATABASE_URL.
    # Do not silently synthesize credentials in an unadmitted process.
    from core.auth import browser_session_service as browser_auth
    return _verify_browser_session_with_authority(db, token, browser_auth)


def verify_d1_sql_pc5_principal(db, bearer: str, *, clock=lambda: datetime.now(timezone.utc)):
    """Compose independently validated database/session authorities.

    This function is not a FastAPI dependency until migration, PC5 mappings,
    least-privilege roles and tenant-scoped producer adapters are admitted.
    """
    readers = D1SQLAuthorityReaders(db)
    return verify_browser_to_pc5_binding(
        bearer,
        verify_browser_access=lambda token: verified_browser_session_from_sql(db, token),
        read_server_owned_link=readers.read_server_owned_link,
        read_pc5_session=readers.read_pc5_session,
        read_pc5_identity_status=readers.read_pc5_identity_status,
        clock=clock,
    )
