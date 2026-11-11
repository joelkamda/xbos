"""Nonoperative PA D2 Blueprint v1 acceptance/readiness candidate.

Pure source functions. Callers MUST provide independently authenticated producer
readbacks; these types do NOT authenticate receipts or authorize activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping
import json
import re

SCHEMA = "xcomp.MerchantBlueprint.v1"
_SECRET = re.compile(r"(secret|password|private.key|api.key|access.token|client.secret|credential)", re.I)
_PROOF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,255}$")


class BlueprintRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AcceptedBlueprint:
    blueprint_id: str
    revision: int
    tenant_id: int | None
    merchant_uuid: str | None
    profile: str
    digest: str
    idempotency_key: str
    canonical_json: str


@dataclass(frozen=True)
class AuthorityReadback:
    """Already verified by trusted PC1/PK/PC4/PC5/PA server adapters, not client input."""
    issuer: str
    tenant_id: int
    merchant_uuid: str
    principal_ref: str
    proof_ref: str
    expires_at: int
    active: bool
    authorized: bool
    assurance_level: int = 0


@dataclass(frozen=True)
class Readiness:
    state: str
    reasons: tuple[str, ...]
    blueprint_digest: str
    effective: bool = False


def _reject_secrets(v: Any) -> None:
    if isinstance(v, dict):
        for key, child in v.items():
            if _SECRET.search(key):
                raise BlueprintRejected("RAW_SECRET_FIELD")
            _reject_secrets(child)
    elif isinstance(v, list):
        for child in v:
            _reject_secrets(child)


def accept_blueprint(value: Mapping[str, Any]) -> AcceptedBlueprint:
    """Capture immutable canonical JSON; no insert, activation, or provider call."""
    try:
        obj = json.loads(json.dumps(value, allow_nan=False))
        if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
            raise BlueprintRejected("SCHEMA_MISMATCH")
        if obj.get("nonoperative") is not True or obj.get("actual_d2_activation_authorized") is not False:
            raise BlueprintRejected("OPERATIVE_CLAIM")
        _reject_secrets(obj)
        bid = obj["blueprint_id"]
        rev = obj["revision"]
        tenant = obj["tenant"]
        profile = obj["merchant_profile"]
        idem = obj["idempotency"]["command_key"]
        if not isinstance(bid, str) or not bid.strip() or type(rev) is not int or rev < 1:
            raise BlueprintRejected("REVISION_OR_ID")
        if not isinstance(idem, str) or not _PROOF.fullmatch(idem):
            raise BlueprintRejected("IDEMPOTENCY_KEY")
        if profile not in ("restaurant", "payments_only"):
            raise BlueprintRejected("PROFILE")
        tid, mid = tenant["numeric_id"], tenant["merchant_public_uuid"]
        if tid is not None and (type(tid) is not int or tid < 1):
            raise BlueprintRejected("TENANT_ID")
        if mid is not None and (not isinstance(mid, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", mid)):
            raise BlueprintRejected("MERCHANT_UUID")
        if (tid is None) != (mid is None):
            raise BlueprintRejected("PARTIAL_TENANT_BINDING")
        packs, template = obj["packs"], obj["template"]
        if not isinstance(packs, list) or not packs or not isinstance(template, dict):
            raise BlueprintRejected("PACK_STRUCTURE")
        pack_codes = []
        for pack in packs:
            pack_codes.append(pack["code"])
            if any(pack.get(key) is not None for key in ("manifest_sha256", "certification_evidence_ref")):
                # Only source-design fixtures are admissible in this nonoperative candidate.
                raise BlueprintRejected("UNVERIFIED_PACK_CLAIM")
        if len(pack_codes) != len(set(pack_codes)) or template["code"] in pack_codes:
            raise BlueprintRejected("TEMPLATE_AS_PACK")
        if profile == "payments_only":
            if tid is not None or set(pack_codes) != {"neutral.foundation", "neutral.payments"}:
                raise BlueprintRejected("PAYMENTS_ONLY_FIXTURE_SCOPE")
            if template["code"] != "neutral.payments_only":
                raise BlueprintRejected("PAYMENTS_ONLY_TEMPLATE")
            policy = obj["business_policy"]
            if not policy["finance_kernel_required"] or policy["tenant_overrides"].get("business_day_start") is not None or policy["tenant_overrides"].get("kitchen") is not None:
                raise BlueprintRejected("RESTAURANT_POLICY_LEAK")
        if profile == "restaurant":
            if tid != 910001 or mid != "4b196022-55a1-548c-b122-f1f9e4b78bea":
                raise BlueprintRejected("SYNTHETIC_RESTAURANT_BINDING")
            if pack_codes != ["industry.restaurant"] or template["code"] != "restaurant.counter_service":
                raise BlueprintRejected("RESTAURANT_PACK_TEMPLATE")
        state = obj["desired_vs_effective"]
        if state.get("effective") is not False or obj["owner_consent"].get("state") != "PENDING":
            raise BlueprintRejected("EFFECTIVE_OR_CONSENT_CLAIM")
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return AcceptedBlueprint(bid, rev, tid, mid, profile, sha256(canonical.encode("utf-8")).hexdigest(), idem, canonical)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, BlueprintRejected):
            raise
        raise BlueprintRejected("INVALID_BLUEPRINT_SHAPE") from exc


def evaluate_readiness(
    accepted: AcceptedBlueprint,
    readbacks: Mapping[str, AuthorityReadback],
    *,
    authenticated_principal: str | None,
    requested_tenant: int | None,
    now_epoch: int,
    prior_command_digest: str | None = None,
) -> Readiness:
    """Fail closed: no authority can originate from a client-side Blueprint."""
    reasons: list[str] = []
    if not authenticated_principal:
        reasons.append("UNAUTHENTICATED")
    if accepted.tenant_id is None or accepted.merchant_uuid is None:
        reasons.append("TENANT_UNISSUED")
    if requested_tenant != accepted.tenant_id or requested_tenant is None:
        reasons.append("WRONG_TENANT")
    if prior_command_digest is not None and prior_command_digest != accepted.digest:
        reasons.append("IDEMPOTENCY_CONFLICT")
    required = ("PC1", "PK", "PC4", "PC5", "PA")
    for issuer in required:
        proof = readbacks.get(issuer)
        if proof is None:
            reasons.append(issuer + "_PROOF_MISSING")
            continue
        if proof.issuer != issuer or not _PROOF.fullmatch(proof.proof_ref or ""):
            reasons.append(issuer + "_PROOF_INVALID")
        if not proof.active or not proof.authorized or proof.expires_at <= now_epoch:
            reasons.append(issuer + "_DENIED_OR_EXPIRED")
        if proof.tenant_id != accepted.tenant_id or proof.merchant_uuid != accepted.merchant_uuid:
            reasons.append(issuer + "_SCOPE_MISMATCH")
        if proof.principal_ref != authenticated_principal:
            reasons.append(issuer + "_PRINCIPAL_MISMATCH")
        if issuer == "PC5" and proof.assurance_level < 2:
            reasons.append("PC5_INSUFFICIENT_ASSURANCE")
    # Even with all receipts, this remains a nonoperative LOCAL preflight.
    return Readiness("BLOCKED" if reasons else "SOURCE_PREFLIGHT_ONLY", tuple(dict.fromkeys(reasons)), accepted.digest)
