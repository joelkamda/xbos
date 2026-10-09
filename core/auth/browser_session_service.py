"""XBOS browser-session v1. Server registry is the refresh and access authority.

Never log raw tokens. Non-browser JWT profile is not modified.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt
from sqlalchemy.orm import Session

from settings import settings
from core.auth.auth_service import AuthService
from core.auth.browser_session_model import BrowserSession
from core.tenants.tenant_model import Branch, Tenant
from core.users.user_model import User

REFRESH_SECONDS = 30 * 24 * 3600
ACCESS_SECONDS = 15 * 60
GRACE_SECONDS = 10


class BrowserSessionDenied(Exception):
    pass


class BrowserConcurrentRefresh(BrowserSessionDenied):
    """One previous generation within the bounded concurrent grace window."""


def now_utc():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def current_authority(db: Session, row: BrowserSession):
    user = db.get(User, row.user_id)
    tenant = db.get(Tenant, row.tenant_id)
    branch = db.get(Branch, row.branch_id)
    if (
        not user or not user.is_active or user.tenant_id != row.tenant_id
        or user.branch_id != row.branch_id or not tenant or not branch
        or branch.tenant_id != row.tenant_id or not branch.is_active
    ):
        raise BrowserSessionDenied("CONTEXT_REVOKED")
    permissions = AuthService().resolve_effective_permissions(db, user.role)
    return user, tenant, branch, permissions


def live_session(db: Session, session_id: str, *, lock=False):
    query = db.query(BrowserSession).filter(BrowserSession.session_id == session_id)
    if lock:
        query = query.with_for_update()
    row = query.one_or_none()
    if not row or row.revoked_at is not None or aware(row.expires_at) <= now_utc():
        raise BrowserSessionDenied("SESSION_NOT_ACTIVE")
    return row


def issue_token(payload, seconds: int):
    timestamp = now_utc()
    return jwt.encode(
        {**payload, "iat": timestamp, "exp": timestamp + timedelta(seconds=seconds)},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str, expected_type: str):
    try:
        value = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if value.get("type") != expected_type:
            raise BrowserSessionDenied("TOKEN_TYPE_INVALID")
        return value
    except BrowserSessionDenied:
        raise
    except Exception as exc:
        raise BrowserSessionDenied("TOKEN_INVALID") from exc


def browser_access(row, permissions, role):
    return issue_token(
        {"type": "browser_access", "sub": str(row.user_id),
         "sid": row.session_id, "tenant_id": row.tenant_id,
         "branch_id": row.branch_id, "role": role, "permissions": permissions},
        ACCESS_SECONDS,
    )


def browser_refresh(row, jti):
    seconds = max(1, int((aware(row.expires_at) - now_utc()).total_seconds()))
    return issue_token(
        {"type": "browser_refresh", "sub": str(row.user_id),
         "sid": row.session_id, "jti": jti,
         "tenant_id": row.tenant_id, "branch_id": row.branch_id},
        seconds,
    )


def create_session(db: Session, user_id: int, tenant_id: int, branch_id: int):
    timestamp = now_utc()
    row = BrowserSession(
        session_id=str(uuid4()), user_id=user_id, tenant_id=tenant_id,
        branch_id=branch_id, created_at=timestamp,
        expires_at=timestamp + timedelta(seconds=REFRESH_SECONDS),
        current_refresh_jti=uuid4().hex, last_rotated_at=timestamp,
    )
    db.add(row)
    db.flush()
    user, _tenant, _branch, permissions = current_authority(db, row)
    refresh_token = browser_refresh(row, row.current_refresh_jti)
    access_token = browser_access(row, permissions, user.role)
    db.commit()
    return row, access_token, refresh_token


def continue_session(db: Session, token: str):
    claims = decode_token(token, "browser_refresh")
    sid = claims.get("sid")
    jti = claims.get("jti")
    if not isinstance(sid, str) or not isinstance(jti, str):
        raise BrowserSessionDenied("INVALID_SESSION_CLAIMS")
    row = live_session(db, sid, lock=True)
    if (claims.get("sub") != str(row.user_id)
        or claims.get("tenant_id") != row.tenant_id
        or claims.get("branch_id") != row.branch_id):
        raise BrowserSessionDenied("SESSION_CONTEXT_MISMATCH")
    user, _tenant, _branch, permissions = current_authority(db, row)
    if jti != row.current_refresh_jti:
        if (
            jti == row.previous_refresh_jti
            and row.previous_refresh_valid_until is not None
            and aware(row.previous_refresh_valid_until) >= now_utc()
        ):
            raise BrowserConcurrentRefresh("CONCURRENT_REFRESH_RETRY")
        row.revoked_at = now_utc()
        row.revocation_reason = "REFRESH_REPLAY"
        db.commit()
        raise BrowserSessionDenied("REFRESH_REPLAY_REVOKED")
    timestamp = now_utc()
    row.previous_refresh_jti = row.current_refresh_jti
    row.previous_refresh_valid_until = timestamp + timedelta(seconds=GRACE_SECONDS)
    row.current_refresh_jti = uuid4().hex
    row.last_rotated_at = timestamp
    refresh_token = browser_refresh(row, row.current_refresh_jti)
    access_token = browser_access(row, permissions, user.role)
    db.commit()
    return row, access_token, refresh_token


def validate_browser_access(db: Session, token: str):
    claims = decode_token(token, "browser_access")
    sid = claims.get("sid")
    if not isinstance(sid, str):
        raise BrowserSessionDenied("SESSION_ID_REQUIRED")
    row = live_session(db, sid)
    if (claims.get("sub") != str(row.user_id)
        or claims.get("tenant_id") != row.tenant_id
        or claims.get("branch_id") != row.branch_id):
        raise BrowserSessionDenied("SESSION_CONTEXT_MISMATCH")
    user, _tenant, _branch, permissions = current_authority(db, row)
    return {"user_id": user.id, "tenant_id": row.tenant_id,
            "branch_id": row.branch_id, "role": user.role,
            "permissions": permissions}


def revoke_session(db: Session, token: str | None):
    if not token:
        return
    try:
        claims = decode_token(token, "browser_refresh")
        sid = claims.get("sid")
        row = db.query(BrowserSession).filter(BrowserSession.session_id == sid).with_for_update().one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = now_utc()
            row.revocation_reason = "LOGOUT"
            db.commit()
    except BrowserSessionDenied:
        return
