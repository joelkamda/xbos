"""SWES Track A: source-isolated registered TEST merchant canonical takeaway order.

No direct R1 order INSERT, no mock payment, no PA state promotion, no protected
RELEASE V2 use. The authoritative PC2 contact represents the *actual* previously
Twilio-signed sender through the nonreversible CC sender digest, not a claimed
telephone number or a fictional customer identity.
"""
# ruff: noqa: B008 - standard FastAPI dependency injection signatures
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.platform.interaction.contracts import (
    InteractionContextBinding,
    PublicAuthorityReference,
)
from core.platform.interaction.sql_repository import SQLInteractionRepository
from core.platform.party.contracts import AddPartyContact, CreatePerson
from core.platform.party.service import PartyAuthority
from core.platform.party.sql_repository import SQLPartyRepository
from database import get_db

from .contracts import CONTACT_PURPOSE, H1BError
from .draft_order import CustomerChannelDraftOrderAuthority
from .swes_track_a_registered_order_scope import (
    _RENDER,
    FLAG,
    LOCATION,
    MERCHANT,
    TENANT,
    qualify_registered_test_order_scope,
)

# Only the trusted CC service, after verifying the signed provider test-order
# action, may invoke this endpoint. A greeting can never authorize an order.
PATH = "/internal/swes/track-a-sandbox/canonical-order"
APPROVED_SOURCE_SHA = "XAFPAY_SWES_TRACK_A_APPROVED_DEPLOY_SHA"
ORDER_ACTION = "order wnd test"
_RECEIPT = "xafpay.cc.hosted_pg17_signed_twilio_receipt"
_SOURCE = "xafpay.customer_channel.signed_twilio"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
router = APIRouter(tags=["SWES TEST ONLY"])

_SOURCE_SQL = text("""
SELECT b.source_reference, b.source_hash, b.provenance_reference,
       b.effective_from, b.expires_at,
       i.public_id session_public_id, cp.public_id participant_public_id,
       e.opaque_subject sender_digest
FROM public.ia0_interaction_context_bindings b
JOIN public.ia0_interaction_sessions i
  ON i.tenant_id=b.tenant_id AND i.id=b.interaction_session_id
JOIN public.ia0_conversation_participants cp
  ON cp.tenant_id=i.tenant_id AND cp.id=i.participant_id
 AND b.participant_id=cp.id AND cp.conversation_id=i.conversation_id
JOIN public.ia0_external_channel_identities e
  ON e.tenant_id=b.tenant_id
 AND e.public_id::text=cp.actor_reference
WHERE b.tenant_id=:tenant AND b.public_id=:context
 AND b.correlation_id=:correlation
 AND b.source_authority=:source
 AND b.purpose_code='restaurant.customer_channel.checkout'
 AND b.provenance_authority=:provenance
 AND b.source_version='v1' AND b.ended_at IS NULL
 AND b.expires_at>now() AND i.lifecycle_status='active'
 AND i.verification_state='channel_verified'
 AND i.identity_resolution_state='channel_identified'
 AND i.closed_at IS NULL AND i.expires_at>now()
 AND cp.participant_kind='external_channel_identity'
 AND cp.actor_authority='ia0.external_channel_identity'
 AND e.channel_kind='twilio_whatsapp'
 AND e.source_code=:source AND e.lifecycle_status='active'
 AND e.resolution_state='channel_identified'
""")

_CATALOG = text("""
SELECT e.public_id item_ref, p.amount amount, p.currency currency
FROM public.pa_merchants m
JOIN public.restaurant_customer_catalog_read_bindings b
  ON b.tenant_id=m.tenant_id AND b.merchant_public_id=m.public_id
JOIN public.so1_catalogs c
  ON c.tenant_id=b.tenant_id AND c.public_id=b.catalog_public_id
JOIN public.so1_catalog_entries e
  ON e.tenant_id=c.tenant_id AND e.catalog_id=c.id
JOIN public.so1_prices p
  ON p.tenant_id=e.tenant_id
 AND p.atomic_unit_id=e.atomic_unit_id AND p.price_code=b.price_code
WHERE m.tenant_id=:tenant AND m.public_id=:merchant
 AND m.administration_state='registered'
 AND b.location_id=:location AND b.active=true AND c.active=true
 AND e.enabled=true AND p.active=true
 AND p.effective_from<=now()
 AND (p.effective_to IS NULL OR now()<p.effective_to)
 AND p.amount=1000 AND p.currency='XAF'
""")

_EXISTING_CONTACT = text("""
SELECT b.public_id
FROM public.ia0_interaction_context_bindings b
JOIN public.ia0_interaction_sessions i
  ON i.tenant_id=b.tenant_id AND i.id=b.interaction_session_id
WHERE b.tenant_id=:tenant AND i.public_id=:session
 AND b.source_authority='pc2.party_contact'
 AND b.source_reference=:contact
 AND b.purpose_code='restaurant.customer_channel.contact'
 AND b.ended_at IS NULL AND b.expires_at>now()
""")

_READBACK = text("""
SELECT o.public_id, o.lifecycle_status,
       coalesce(sum(l.quantity*l.unit_price_snapshot),0) amount,
       count(l.id) line_count,
       count(DISTINCT l.currency) currency_count,
       min(l.currency) currency
FROM public.r1_restaurant_orders o
LEFT JOIN public.r1_restaurant_order_lines l
  ON l.tenant_id=o.tenant_id AND l.order_id=o.id
WHERE o.tenant_id=:tenant AND o.public_id=:order
GROUP BY o.public_id,o.lifecycle_status
""")


def _owner_approved_source(env) -> str | None:
    value = env.get(APPROVED_SOURCE_SHA)
    # Owner must separately pin the independently verified Render deployment;
    # never derive approval from caller input or RENDER_GIT_COMMIT alone.
    if (
        env.get(FLAG) != "1"
        or not isinstance(value, str) or not _SHA.fullmatch(value)
        or env.get("RENDER_GIT_COMMIT") != value
        or any(env.get(k) != v for k, v in _RENDER.items())
    ):
        return None
    return value


def _read_source(db, *, binding: UUID, correlation: UUID, event_id: str):
    rows = db.execute(_SOURCE_SQL, {
        "tenant": TENANT, "context": str(binding),
        "correlation": str(correlation), "source": _SOURCE,
        "provenance": _RECEIPT,
    }).mappings().all()
    if len(rows) != 1:
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=str(correlation))
    info = rows[0]
    if (
        not _HASH.fullmatch(event_id)
        or info["source_reference"] != event_id
        or not isinstance(info["sender_digest"], str)
        or not _HASH.fullmatch(info["sender_digest"])
        or not isinstance(info["source_hash"], str)
        or not _HASH.fullmatch(info["source_hash"])
        or not isinstance(info["provenance_reference"], str)
        or not _HASH.fullmatch(info["provenance_reference"])
    ):
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=str(correlation))
    return info


def _make_sender_bound_contact(db, *, source, event_id: str, now: datetime) -> UUID:
    """PC2+IA0 canonical authority: a pseudonymous *verified* TEST sender.

    Each action is idempotently derived from the signed sender digest.
    No phone number, profile name or invented contact claims are persisted.
    """
    sender = str(source["sender_digest"])
    party = PartyAuthority(SQLPartyRepository(db))
    person = party.create_person(CreatePerson(
        command_key="swes:910001:sender:" + sender,
        tenant_id=TENANT, external_key="twilio-signed-hmac:" + sender,
        given_name="Verified", family_name="Sandbox Tester",
    ))
    contact = party.add_contact(AddPartyContact(
        command_key="swes:910001:contact:" + sender,
        tenant_id=TENANT, party_id=person.party.id,
        contact_type="other", value="twilio-whatsapp-hmac:" + sender,
        valid_from=source["effective_from"].astimezone(timezone.utc).date(),
    ))
    exists = db.execute(_EXISTING_CONTACT, {
        "tenant": TENANT, "session": str(source["session_public_id"]),
        "contact": str(contact.id),
    }).scalars().all()
    if len(exists) > 1:
        raise H1BError("CONTEXT_MISMATCH")
    if exists:
        return UUID(str(exists[0]))

    binding = SQLInteractionRepository(db).insert_context_binding(
        InteractionContextBinding(
            tenant_id=TENANT, public_id=uuid4(),
            interaction_session_public_id=UUID(str(source["session_public_id"])),
            participant_public_id=UUID(str(source["participant_public_id"])),
            source_reference=PublicAuthorityReference("pc2.party_contact", str(contact.id)),
            purpose_code=CONTACT_PURPOSE,
            provenance=PublicAuthorityReference(_RECEIPT, source["provenance_reference"]),
            effective_from=source["effective_from"],
            expires_at=source["expires_at"],
            source_version="v1", source_hash=source["source_hash"],
            correlation_id=UUID(str(source["correlation_ref"])),
        )
    )
    return binding.public_id


def _order_from_verified_context(db, *, scope, event_id: str, correlation: UUID):
    now = datetime.now(timezone.utc)
    source = _read_source(
        db, binding=scope.context_binding_public_id,
        correlation=correlation, event_id=event_id,
    )
    source = dict(source)
    source["correlation_ref"] = str(correlation)
    candidates = db.execute(_CATALOG, {
        "tenant": TENANT, "merchant": str(MERCHANT), "location": LOCATION,
    }).mappings().all()
    if len(candidates) != 1:
        raise H1BError("ORDER_NOT_READY", correlation_ref=str(correlation))
    item = candidates[0]
    if (
        Decimal(str(item["amount"])) != Decimal(1000)
        or item["currency"] != "XAF"
    ):
        raise H1BError("ORDER_NOT_READY", correlation_ref=str(correlation))

    contact = _make_sender_bound_contact(db, source=source, event_id=event_id, now=now)
    authority = CustomerChannelDraftOrderAuthority(db)
    # These three commands invoke the canonical server-pricing and R1 order
    # authorities. They are one caller-owned DB transaction; no direct INSERT.
    draft = authority.create_draft(
        scope=scope, client_command_ref="swes:test:" + event_id + ":draft",
        service_mode="takeaway", contact_ref=contact, at=now,
    )
    if draft["order_state"] == "SUBMITTED":
        order_ref = UUID(str(draft["order_ref"]))
    else:
        if draft["order_state"] != "DRAFT" or draft["lines"]:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=str(correlation))
        updated = authority.mutate_draft(
            scope=scope, draft_ref=UUID(str(draft["draft_ref"])),
            payload={
                "operation": "ADD_LINE",
                "client_command_ref": "swes:test:" + event_id + ":line",
                "expected_draft_version": int(draft["draft_version"]),
                "item_ref": str(item["item_ref"]),
                "quantity": "1", "modifier_refs": [],
            }, at=now,
        )
        if (
            Decimal(str(updated["canonical_total"])) != Decimal(1000)
            or updated["currency"] != "XAF"
        ):
            raise H1BError("ORDER_NOT_READY", correlation_ref=str(correlation))
        confirmation = authority.confirm_draft(
            scope=scope, draft_ref=UUID(str(draft["draft_ref"])), at=now,
        )
        if (
            confirmation.canonical_total != Decimal(1000)
            or confirmation.currency != "XAF"
            or len(confirmation.authoritative_lines) != 1
        ):
            raise H1BError("ORDER_NOT_READY", correlation_ref=str(correlation))
        submitted = authority.submit_draft(
            scope=scope, draft_ref=UUID(str(draft["draft_ref"])),
            confirmation_ref=confirmation.confirmation_ref,
            client_submit_ref="swes:test:" + event_id + ":submit", at=now,
        )
        order_ref = submitted.order_ref

    rows = db.execute(_READBACK, {
        "tenant": TENANT, "order": str(order_ref),
    }).mappings().all()
    if (
        len(rows) != 1 or rows[0]["lifecycle_status"] != "submitted"
        or Decimal(str(rows[0]["amount"])) != Decimal(1000)
        or int(rows[0]["line_count"]) != 1
        or int(rows[0]["currency_count"]) != 1
        or rows[0]["currency"] != "XAF"
    ):
        raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=str(correlation))
    return order_ref


@router.post(PATH)
def create_track_a_canonical_order(request: Request, payload: dict = Body(...),
                                   db=Depends(get_db)):
    try:
        approved = _owner_approved_source(os.environ)
        if approved is None or set(payload) != {
            "context_binding_ref", "correlation_ref", "event_id", "action"
        } or payload["action"] != ORDER_ACTION:
            raise H1BError("SERVICE_AUTH_FORBIDDEN")
        binding = UUID(str(payload["context_binding_ref"]))
        correlation = UUID(str(payload["correlation_ref"]))
        event_id = str(payload["event_id"])
        if (
            request.headers.get("X-CC-Event-Id") != event_id
            or request.headers.get("X-Correlation-Ref") != str(correlation)
            or not request.headers.get("Authorization", "").startswith("Bearer ")
        ):
            raise H1BError("SERVICE_AUTH_FORBIDDEN")
        # Real, distinct checkout principal; never use the IA0 ingestion token.
        scope = qualify_registered_test_order_scope(
            db, authorization_header=request.headers["Authorization"],
            context_binding_ref=binding, correlation_ref=correlation,
            expected_deployed_sha=approved, environ=os.environ,
        )
        order_ref = _order_from_verified_context(
            db, scope=scope, event_id=event_id, correlation=correlation,
        )
        db.commit()
        return JSONResponse(status_code=201, content={
            "schema": "xafpay.wnd.swes.track_a.canonical_order.v1",
            "order_ref": str(order_ref),
            "order_state": "SUBMITTED",
            "payment_state": "NOT_INITIATED",
            "tenant_id": TENANT, "location_id": LOCATION,
            "merchant_public_id": str(MERCHANT),
            "currency": "XAF", "canonical_amount": "1000",
            "context_binding_ref": str(binding), "correlation_ref": str(correlation),
        })
    except (H1BError, ValueError, KeyError, TypeError):
        db.rollback()
        return JSONResponse(status_code=403, content={"detail": "TRACK_A_ORDER_NOT_AUTHORIZED"})
    except Exception:  # noqa: BLE001 - fail closed; no secret/SQL leakage
        db.rollback()
        return JSONResponse(status_code=503, content={"detail": "TRACK_A_ORDER_UNAVAILABLE"})


def install_track_a_order(app, *, environ=None) -> bool:
    env = environ if environ is not None else os.environ
    if _owner_approved_source(env) is None:
        return False
    if getattr(app.state, "swes_track_a_order_installed", False):
        raise RuntimeError("TRACK_A_ORDER_ALREADY_INSTALLED")
    app.include_router(router)
    app.state.swes_track_a_order_installed = True
    return True
