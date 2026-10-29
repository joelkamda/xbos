"""PCR V17 M1: DORMANT local-only, no-secret WND admission prototype.

Not registered in startup, HTTP routing, jobs or database composition.
The caller's booleans are ONLY fake-local assertions, never live attestation.
A future independently authorized owner/reader must produce signed evidence.
No environment, credential, database, network or filesystem operations here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256

EXPECTED_TENANT = 910001  # local fake identity; hosted existence is UNPROVEN
CURRENT_SOURCE_PIN = "4cf6c89ce37410e5d289775e5baa98406cedf4f3"
MAX_TTL = timedelta(minutes=5)
OFFLINE_ONLY = True
DEFAULT_ENABLED = False

# Typed allowlist: NOT a query, API schema, DB projection or proof of live ACLs.
FLAGS: tuple[str, ...] = (
    "owner_authenticated",
    "runtime_source_verified",
    "deployed_schema_verified",
    "reader_authenticated",
    "reader_effective",
    "reader_read_only",
    "reader_no_owner_writer_bypass",
    "rls_isolation_verified",
    "isolated_synthetic_tenant",
    "merchant_location_branch_bound",
    "service_reference_match",
    "checkout_permission_effective",
    "checkout_context_active",
    "catalog_retail_xaf",
    "server_price_version_bound",
    "r5c_disabled",
    "r5h_disabled",
    "provider_egress_disabled",
    "audit_custody_verified",
)
COUNTS: tuple[str, ...] = (
    "synthetic_tenant_count",
    "merchant_count",
    "location_branch_count",
    "service_identity_count",
    "checkout_permission_count",
    "checkout_context_count",
    "catalog_binding_count",
)
_ALLOWED = frozenset(FLAGS + COUNTS)
_TICKET = re.compile(r"^[A-Z0-9-]{12,64}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class TrustedLocalAdmission:
    """Fake local input. NOT a way to authenticate a live principal."""

    tenant_id: int
    synthetic_scope_preapproved: bool
    source_pin: str
    runtime_pin: str
    issuer_attested: bool
    schema_pin_attested: bool
    reader_acl_attested: bool
    event_ticket: str
    issued_at: datetime
    expires_at: datetime


@dataclass
class OneEventLocalLedger:
    """Process-only test ledger. Not a distributed lease or production audit."""

    _claimed: set[str] = field(default_factory=set)

    def claim_once(self, receipt: str) -> bool:
        if receipt in self._claimed:
            return False
        self._claimed.add(receipt)
        return True


def _utc(value: datetime) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    if value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _hold(code: str) -> dict[str, object]:
    # NEVER echo a selector, identity, raw observation or exception.
    return {"decision": "HOLD", "reason": code, "checks": {}, "audit_receipt": None}


def evaluate_local_fake(
    admission: TrustedLocalAdmission,
    fake_observations: Mapping[str, object],
    *,
    at: datetime,
    ledger: OneEventLocalLedger,
) -> dict[str, object]:
    """Strict fake-only admission calculation; no I/O and no SQL.

    Caller MUST NOT pass real DB rows or secrets; any extra key fails closed.
    Actual schema/ACL/ownership is UNPROVEN until a future protected gate.
    """
    if not isinstance(admission, TrustedLocalAdmission) or not isinstance(ledger, OneEventLocalLedger):
        return _hold("HOLD_UNTRUSTED_ENVELOPE")
    now = _utc(at)
    issued = _utc(admission.issued_at)
    expires = _utc(admission.expires_at)
    if now is None or issued is None or expires is None:
        return _hold("HOLD_TIME")
    if not (
        type(admission.tenant_id) is int
        and admission.tenant_id == EXPECTED_TENANT
        and admission.synthetic_scope_preapproved is True
        and admission.issuer_attested is True
        and admission.schema_pin_attested is True
        and admission.reader_acl_attested is True
    ):
        return _hold("HOLD_OWNER_OR_SYNTHETIC_SCOPE")
    if not (
        isinstance(admission.source_pin, str)
        and isinstance(admission.runtime_pin, str)
        and _SHA.fullmatch(admission.source_pin)
        and admission.source_pin == CURRENT_SOURCE_PIN
        and admission.runtime_pin == admission.source_pin
    ):
        return _hold("HOLD_RELEASE_PIN")
    if not (
        issued <= now < expires
        and timedelta(0) < expires - issued <= MAX_TTL
        and isinstance(admission.event_ticket, str)
        and _TICKET.fullmatch(admission.event_ticket)
    ):
        return _hold("HOLD_LEASE")
    if not isinstance(fake_observations, Mapping):
        return _hold("HOLD_FIELDSET")
    if set(fake_observations) != _ALLOWED:
        return _hold("HOLD_FIELDSET")
    if any(type(fake_observations[k]) is not bool for k in FLAGS):
        return _hold("HOLD_FIELD_TYPE")
    if any(type(fake_observations[k]) is not int or fake_observations[k] != 1 for k in COUNTS):
        return _hold("HOLD_CARDINALITY")
    # True proves nothing in hosting: this is a synthetic scenario test.
    if not all(fake_observations[k] is True for k in FLAGS):
        return _hold("HOLD_EFFECTIVE_PERMISSION_OR_RUNTIME")
    receipt = sha256(
        ("msar-wnd-offline|" + admission.event_ticket + "|" + admission.source_pin)
        .encode("ascii")
    ).hexdigest()[:24]
    if not ledger.claim_once(receipt):
        return _hold("HOLD_REPLAY")
    # Fixed allowlisted boolean output; never includes raw input identities.
    return {
        "decision": "PASS_FAKE_LOCAL_ONLY",
        "reason": "LOCAL_DESIGN_QUALIFIED_NOT_HOSTED",
        "checks": {k: True for k in FLAGS},
        "audit_receipt": receipt,
    }
