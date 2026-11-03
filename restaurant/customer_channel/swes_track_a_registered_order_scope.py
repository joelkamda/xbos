"""R48 Track A: separately authenticated, default-OFF registered TEST merchant scope.

This is a READ-ONLY source component, not a public route or an IA0 receipt
creator. It cannot be installed by an environment switch or caller-supplied
claims: a trusted server-side composition must verify the exact deployed source
independently and supply the source pin. Until independently admitted, no
protected or synthetic order is authorized.

This does NOT replace normal PA-OPERATIONAL merchant resolution, nor the
separately protected RELEASE V2 receipt receiver/transaction fence.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from .contracts import H1BError, TrustedCheckoutScope

TENANT = 910001
LOCATION = 5
MERCHANT = UUID("4b196022-55a1-548c-b122-f1f9e4b78bea")
REFERENCE = "SWES-R2-WND-AUSTIN-TEST-ONLY"
SERVICE = "swes-track-a-customer-channel"
CREDENTIAL_REFERENCE = "env.swes_track_a_order_cc_bearer"
PERMISSION = "restaurant.customer_channel.checkout"
SOURCE = "xafpay.customer_channel.signed_twilio"
PROVENANCE = "xafpay.cc.hosted_pg17_signed_twilio_receipt"
PURPOSE = "restaurant.customer_channel.checkout"
FLAG = "XAFPAY_SWES_TRACK_A_REGISTERED_ORDER_ENABLED"
TOKEN_DIGEST = "XAFPAY_SWES_TRACK_A_ORDER_BEARER_SHA256"
TOKEN_EXPIRES = "XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

_RENDER = {
    "RENDER": "true",
    "RENDER_SERVICE_ID": "srv-db3vej67bikc73ai2080",
    "RENDER_SERVICE_TYPE": "web",
    "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
    "RENDER_GIT_BRANCH": "compat/wnd-demo-cc-r1-legacy-neutral-bridge",
}

_SERVICE_SQL = text("""
SELECT DISTINCT s.id, s.public_id, a.scope_id
FROM public.service_identities s
JOIN public.scoped_role_assignments a
  ON a.principal_id=s.id AND a.tenant_id=s.tenant_id
 AND a.actor_type='service' AND a.status='active'
 AND a.scope_type='location' AND a.scope_id=:location
 AND a.valid_from<=:now AND (a.valid_to IS NULL OR :now<a.valid_to)
JOIN public.authorization_roles r
  ON r.id=a.role_id AND r.tenant_id=s.tenant_id AND r.status='active'
JOIN public.authorization_role_permissions rp
  ON rp.role_id=r.id AND rp.effective_from<=:now
 AND (rp.effective_to IS NULL OR :now<rp.effective_to)
JOIN public.permission_definitions p
  ON p.id=rp.permission_id
WHERE s.tenant_id=:tenant AND s.service_code=:service
  AND s.owner_module='restaurant' AND s.status='active'
  AND s.revoked_at IS NULL AND s.credential_reference=:credential
  AND p.permission_code=:permission AND p.owner_module='restaurant'
  AND p.resource_code='customer_channel' AND p.action_code='checkout'
  AND p.status='active' AND p.required_assurance=1
  AND 'location'=ANY(p.allowed_scopes)
""")

_MERCHANT_SQL = text("""
SELECT public_id, tenant_id, administration_state, external_reference
FROM public.pa_merchants
WHERE tenant_id=:tenant AND public_id=:merchant
  AND administration_state='registered'
  AND external_reference=:external_ref
""")

_IA0_SQL = text("""
SELECT b.public_id, b.tenant_id, b.purpose_code, b.source_authority,
       b.source_reference, b.source_hash, b.source_version,
       b.provenance_authority, b.provenance_reference, b.correlation_id,
       b.effective_from, b.expires_at, b.ended_at,
       i.lifecycle_status AS session_status,
       i.verification_state, i.identity_resolution_state,
       i.expires_at AS session_expires_at, i.closed_at
FROM public.ia0_interaction_context_bindings b
JOIN public.ia0_interaction_sessions i
  ON i.tenant_id=b.tenant_id AND i.id=b.interaction_session_id
JOIN public.ia0_conversation_participants cp
  ON cp.tenant_id=i.tenant_id AND cp.id=i.participant_id
 AND cp.id=b.participant_id AND cp.conversation_id=i.conversation_id
WHERE b.tenant_id=:tenant AND b.public_id=:binding
  AND cp.participant_kind='external_channel_identity'
""")

_STRUCTURE_SQL = text("""
SELECT m.branch_id, m.organization_unit_id,
       l.id AS location_id, t.currency
FROM public.legacy_branch_structural_mappings m
JOIN public.organization_units o
  ON o.tenant_id=m.tenant_id AND o.id=m.organization_unit_id
 AND o.active=true
JOIN public.locations l
  ON l.tenant_id=m.tenant_id AND l.id=m.location_id
 AND l.active=true
JOIN public.tenants t ON t.id=m.tenant_id
WHERE m.tenant_id=:tenant AND m.location_id=:location
""")


def _one(db, query, values, *, trace: str):
    # No role, merchant or context is inferred from caller-controlled JSON.
    rows = db.execute(query, values).mappings().all()
    if len(rows) != 1:
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)
    return rows[0]


def _utc_expiry(value: str, now: datetime, trace: str) -> None:
    try:
        expiry = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace) from exc
    if (
        expiry.tzinfo is None
        or expiry.utcoffset() != timedelta(0)
        or not (now < expiry <= now + timedelta(hours=24))
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)


def qualify_registered_test_order_scope(
    db,
    *,
    authorization_header: str | None,
    context_binding_ref: UUID,
    correlation_ref: UUID,
    expected_deployed_sha: str,
    environ: Mapping[str, str],
    now: datetime | None = None,
) -> TrustedCheckoutScope:
    """Verify a restricted TEST principal + real sender-bound IA0 source.

    Never expose directly as a route. This function does not create IA0 events,
    sessions, fixture credentials, PA permissions, merchant rows or orders.
    The caller must obtain expected_deployed_sha from a trusted release
    controller, NOT from a request or the same unverified environment.
    """
    trace = str(correlation_ref)
    instant = now or datetime.now(timezone.utc)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != timedelta(0)
        or type(context_binding_ref) is not UUID
        or type(correlation_ref) is not UUID
        or str(environ.get(FLAG, "")) != "1"
        or any(environ.get(k) != v for k, v in _RENDER.items())
        or not isinstance(expected_deployed_sha, str)
        or not _COMMIT.fullmatch(expected_deployed_sha)
        or environ.get("RENDER_GIT_COMMIT") != expected_deployed_sha
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)

    digest = str(environ.get(TOKEN_DIGEST, "")).removeprefix("sha256:").lower()
    if (
        not _SHA.fullmatch(digest)
        or not isinstance(authorization_header, str)
        or not authorization_header.startswith("Bearer ")
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)
    token = authorization_header[7:]
    if (
        not 32 <= len(token) <= 256
        or any(ord(x) < 33 or ord(x) > 126 for x in token)
        or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), digest)
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)
    _utc_expiry(environ.get(TOKEN_EXPIRES, ""), instant, trace)

    values = {"tenant": TENANT, "location": LOCATION, "now": instant,
              "service": SERVICE, "credential": CREDENTIAL_REFERENCE,
              "permission": PERMISSION}
    principal = _one(db, _SERVICE_SQL, values, trace=trace)
    if (
        int(principal["scope_id"]) != LOCATION
        or not isinstance(principal["public_id"], (str, UUID))
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)
    service_ref = UUID(str(principal["public_id"]))

    merchant = _one(db, _MERCHANT_SQL, {
        "tenant": TENANT, "merchant": str(MERCHANT),
        "external_ref": REFERENCE,
    }, trace=trace)
    if (
        str(merchant["public_id"]) != str(MERCHANT)
        or int(merchant["tenant_id"]) != TENANT
        or merchant["administration_state"] != "registered"
        or merchant["external_reference"] != REFERENCE
    ):
        raise H1BError("SERVICE_AUTH_FORBIDDEN", correlation_ref=trace)

    source = _one(db, _IA0_SQL, {
        "tenant": TENANT, "binding": str(context_binding_ref),
    }, trace=trace)
    expected = {
        "purpose_code": PURPOSE,
        "source_authority": SOURCE,
        "source_version": "v1",
        "provenance_authority": PROVENANCE,
        "session_status": "active",
        "verification_state": "channel_verified",
        "identity_resolution_state": "channel_identified",
    }
    if any(source.get(k) != v for k, v in expected.items()):
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace)
    if (
        str(source["public_id"]) != str(context_binding_ref)
        or int(source["tenant_id"]) != TENANT
        or str(source["correlation_id"]) != trace
        or not isinstance(source["source_reference"], str)
        or not _SHA.fullmatch(source["source_reference"])
        or not isinstance(source["source_hash"], str)
        or not _SHA.fullmatch(source["source_hash"])
        or not isinstance(source["provenance_reference"], str)
        or not _SHA.fullmatch(source["provenance_reference"])
        or source["ended_at"] is not None
        or source["closed_at"] is not None
        or source["effective_from"] > instant
        or source["expires_at"] is None
        or source["session_expires_at"] is None
        or not (instant < source["expires_at"]
                and instant < source["session_expires_at"])
    ):
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace)

    structure = _one(db, _STRUCTURE_SQL, {
        "tenant": TENANT, "location": LOCATION
    }, trace=trace)
    if (
        int(structure["location_id"]) != LOCATION
        or structure["currency"] != "XAF"
        or int(structure["branch_id"]) <= 0
        or int(structure["organization_unit_id"]) <= 0
    ):
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace)

    return TrustedCheckoutScope(
        TENANT,
        int(structure["branch_id"]),
        int(structure["organization_unit_id"]),
        LOCATION,
        MERCHANT,
        context_binding_ref,
        service_ref,
        "XAF",
        trace,
    )
