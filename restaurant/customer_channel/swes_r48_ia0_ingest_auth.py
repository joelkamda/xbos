"""R48 restricted CC ingest: server-owned bearer AND DB role; fail closed.

No caller-supplied identity, scope or verification Boolean can grant access.
Receipt proof remains a separate, independently implemented CC trust boundary.
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timezone

from sqlalchemy import text

from .swes_r48_cc_event_validation import TENANT, CCEventRejected

_PERMISSION = "restaurant.customer_channel.ia0_ingest"
_SERVICE = "customer-channel"
_REFERENCE = "env.xafpay_cc_wnd_ia0_ingest_token"
_DIGEST_ENV = "XAFPAY_CC_WND_IA0_INGEST_TOKEN_SHA256"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def authorize_cc_ingest(db, *, bearer: str | None, at: datetime | None = None) -> bool:
    """Require a distinct secret plus one active permission-scoped DB identity.

    The caller must invoke this using its actual Authorization bearer, never
    derive it from headers such as claimed principal or audience.
    """
    digest = (os.environ.get(_DIGEST_ENV) or "").strip().lower()
    digest = digest.removeprefix("sha256:")
    if not _DIGEST.fullmatch(digest) or not isinstance(bearer, str):
        raise CCEventRejected("INGEST_AUTH_NOT_CONFIGURED")
    if len(bearer) < 32 or len(bearer) > 512:
        raise CCEventRejected("INGEST_AUTH_FORBIDDEN")
    if not hmac.compare_digest(hashlib.sha256(bearer.encode()).hexdigest(), digest):
        raise CCEventRejected("INGEST_AUTH_FORBIDDEN")
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CCEventRejected("INGEST_AUTH_FORBIDDEN")
    candidates = db.execute(text("""
        SELECT DISTINCT s.id, a.scope_id
        FROM service_identities s
        JOIN scoped_role_assignments a
          ON a.principal_id=s.id AND a.tenant_id=s.tenant_id
         AND a.actor_type='service' AND a.scope_type='location'
         AND a.scope_id=5 AND a.status='active'
         AND a.valid_from<=:at AND (a.valid_to IS NULL OR :at<a.valid_to)
        JOIN authorization_roles r
          ON r.id=a.role_id AND r.tenant_id=s.tenant_id AND r.status='active'
        JOIN authorization_role_permissions rp
          ON rp.role_id=r.id AND rp.effective_from<=:at
         AND (rp.effective_to IS NULL OR :at<rp.effective_to)
        JOIN permission_definitions p ON p.id=rp.permission_id
        WHERE s.tenant_id=:tenant AND s.service_code=:service
          AND s.owner_module='restaurant' AND s.status='active'
          AND s.revoked_at IS NULL AND s.credential_reference=:ref
          AND p.permission_code=:permission AND p.status='active'
          AND p.owner_module='restaurant' AND p.resource_code='customer_channel'
          AND p.action_code='ia0_ingest' AND p.required_assurance=1
          AND 'location'=ANY(p.allowed_scopes)
    """), {"tenant": TENANT, "service": _SERVICE,
           "ref": _REFERENCE, "permission": _PERMISSION, "at": now}).all()
    if len(candidates) != 1:
        raise CCEventRejected("INGEST_SCOPE_NOT_AUTHORIZED")
    return True
