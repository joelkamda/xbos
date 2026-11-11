"""D2 SOURCE-ONLY deterministic MerchantBlueprint -> ActivationPlan preview.

No repository, network, wall-clock, installation or authorization effects.
Caller-provided producer snapshots are synthetic LOCAL TEST DOUBLE inputs only.
Even an all-green preview is never an operative grant, consent, or PK6 apply plan.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from .pk456_service import _REQUIRED_CERTIFICATION_CHECKS

_SHA = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^\d+(?:\.\d+){1,3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_PROFILE = {
    "restaurant": ("WND_RESTAURANT", "restaurant.counter_service", (("industry.restaurant", "1.0.0"),)),
    "payments_only": ("PAYMENTS_ONLY", "neutral.payments_only", (("neutral.foundation", "1.0.0"), ("neutral.payments", "1.0.0"))),
}
_SECRET_KEYS = {"password", "private_key", "api_key", "access_token", "client_secret",
                "credential", "secret_value", "provider_token", "authorization_header"}
_PRODUCERS = ("pc1", "pa", "pk", "pc4", "pc5", "policy")

class ActivationPlanCompilationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ActivationPlanCompilationError(code)

def _obj(value: Any, code: str) -> Mapping[str, Any]:
    _require(isinstance(value, dict), code)
    return value

def _read(obj: Mapping[str, Any], *path: str) -> Any:
    for key in path:
        obj = _obj(obj, "PK_D2_MALFORMED_FIELD_" + "_".join(path))
        _require(key in obj, "PK_D2_MISSING_" + "_".join(path))
        obj = obj[key]
    return obj

def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ActivationPlanCompilationError("PK_D2_NOT_CANONICAL_JSON") from exc

def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()

def _scan_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            _require(name not in _SECRET_KEYS and not name.endswith("_password")
                     and not name.endswith("_secret"), "PK_D2_INLINE_SECRET_FORBIDDEN")
            _scan_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_secrets(item)

def _parse_time(value: Any) -> datetime:
    _require(isinstance(value, str), "PK_D2_INVALID_TIME")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActivationPlanCompilationError("PK_D2_INVALID_TIME") from exc
    _require(result.tzinfo is not None and result.utcoffset() is not None,
             "PK_D2_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)

def _as_sha(value: Any, code: str) -> str:
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None, code)
    return value

def _as_version(value: Any, code: str) -> str:
    _require(isinstance(value, str) and _VERSION.fullmatch(value) is not None, code)
    return value

def _identity_rows(value: Any, *, code: str) -> tuple[tuple[str, str], ...]:
    _require(isinstance(value, list) and bool(value), code)
    items: list[tuple[str, str]] = []
    for row in value:
        row = _obj(row, code)
        name = _read(row, "code")
        _require(isinstance(name, str) and bool(name.strip()), code)
        items.append((name, _as_version(_read(row, "version"), code)))
    _require(len(set(items)) == len(items) and len({code for code, _ in items}) == len(items),
             "PK_D2_DUPLICATE_PACK")
    return tuple(sorted(items))

def _checked_producer(readbacks: Mapping[str, Any], producer: str, now: datetime) -> Mapping[str, Any]:
    row = _obj(_read(readbacks, producer), "PK_D2_READBACK_REQUIRED_" + producer.upper())
    _require(row.get("producer") == producer.upper(), "PK_D2_WRONG_PRODUCER_" + producer.upper())
    _require(row.get("proof_grade") == "SYNTHETIC_ONLY",
             "PK_D2_UNVERIFIED_RUNTIME_READBACK_FORBIDDEN")
    _require(_parse_time(_read(row, "as_of")) <= now < _parse_time(_read(row, "expires_at")),
             "PK_D2_STALE_" + producer.upper())
    _as_sha(_read(row, "source_digest"), "PK_D2_SOURCE_DIGEST_" + producer.upper())
    return row

def compile_activation_plan(
    blueprint: Mapping[str, Any],
    readbacks: Mapping[str, Any],
    *,
    evaluated_at: str,
    xafchat_mode: str = "off",
    replay: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure source PREVIEW. Does not bind actual authoritative runtime sources."""
    bp = _obj(blueprint, "PK_D2_BLUEPRINT_REQUIRED")
    facts = _obj(readbacks, "PK_D2_READBACKS_REQUIRED")
    _scan_secrets(bp)
    _scan_secrets(facts)
    _require(bp.get("proof_grade") == "NONOPERATIVE_DESIGN_ONLY",
             "PK_D2_NONOPERATIVE_BLUEPRINT_REQUIRED")
    _require(not bp.get("desired_vs_effective", {}).get("effective"),
             "PK_D2_FORGED_EFFECTIVE_STATUS")
    now = _parse_time(evaluated_at)
    _require(xafchat_mode in {"off", "on", "pause"}, "PK_D2_INVALID_XAFCHAT_MODE")
    _require(type(bp.get("revision")) is int and bp["revision"] > 0
             and isinstance(bp.get("blueprint_id"), str) and bool(bp["blueprint_id"]),
             "PK_D2_BLUEPRINT_REVISION_INVALID")
    profile = bp.get("merchant_profile")
    _require(profile in _PROFILE, "PK_D2_UNSUPPORTED_PROFILE")
    alias, template_name, mandatory = _PROFILE[profile]
    _require(bp.get("pack_alias") == alias, "PK_D2_PACK_ALIAS_MISMATCH")
    desired_packs = _identity_rows(_read(bp, "packs"), code="PK_D2_PACK_INVALID")
    _require(desired_packs == tuple(sorted(mandatory)), "PK_D2_INCOMPATIBLE_PACK_GRAPH")
    selected_template = _obj(_read(bp, "template"), "PK_D2_TEMPLATE_REQUIRED")
    _require(selected_template.get("code") == template_name
             and _as_version(selected_template.get("version"), "PK_D2_TEMPLATE_VERSION") == "1.0.0",
             "PK_D2_TEMPLATE_PROFILE_CONFLICT")
    _require(template_name not in (code for code, _ in desired_packs),
             "PK_D2_TEMPLATE_IS_NOT_A_PACK")
    _require(_read(bp, "business_policy", "finance_kernel_required") is True,
             "PK_D2_NEUTRAL_FINANCE_REQUIRED")
    tenant = _obj(_read(bp, "tenant"), "PK_D2_TENANT_REQUIRED")
    tenant_id = tenant.get("numeric_id")
    _require(type(tenant_id) is int and tenant_id > 0
             and isinstance(tenant.get("merchant_public_uuid"), str)
             and bool(tenant["merchant_public_uuid"]), "PK_D2_TENANT_UNISSUED")
    _require(tenant.get("production_wnd_tenant_2") is False,
             "PK_D2_PRODUCTION_WND_TENANT_FORBIDDEN")
    if profile == "payments_only":
        rules = _obj(_read(bp, "business_policy", "tenant_overrides"),
                     "PK_D2_PAYMENT_POLICY_REQUIRED")
        _require(rules.get("business_day_start") is None and not rules.get("shifts")
                 and rules.get("kitchen") is None and not rules.get("restaurant_pack_applied"),
                 "PK_D2_WND_POLICY_INHERITANCE_DENIED")
        modules = list(_read(bp, "modules", "required"))
        _require(not any(any(fragment in str(module).lower()
                             for fragment in ("kitchen", "stock", "restaurant", "inventory"))
                         for module in modules), "PK_D2_RESTAURANT_MODULE_LEAK")
    _require(isinstance(_read(bp, "jurisdiction", "country"), str)
             and _COUNTRY.fullmatch(bp["jurisdiction"]["country"]) is not None,
             "PK_D2_COUNTRY_INVALID")
    country = bp["jurisdiction"]["country"]
    for p in _PRODUCERS:
        _checked_producer(facts, p, now)
    pc1, pa, pk, pc4, pc5, policy = (facts[x] for x in _PRODUCERS)
    _require(pc1.get("tenant_id") == tenant_id
             and pc1.get("merchant_public_uuid") == tenant["merchant_public_uuid"]
             and pc1.get("profile") == profile and pc1.get("issued") is True,
             "PK_D2_PC1_TENANT_BINDING_DENIED")
    branch_id = pc1.get("branch_id")
    _require(type(branch_id) is int and branch_id > 0
             and tenant.get("branch_id") in (None, branch_id), "PK_D2_PC1_BRANCH_INVALID")
    _require(pa.get("tenant_id") == tenant_id and pa.get("lifecycle") == "ONBOARDING_READY"
             and pa.get("owner_consent") == "APPROVED"
             and isinstance(pa.get("owner_proof_ref"), str) and bool(pa.get("owner_proof_ref"))
             and pa.get("subscription") == "ACTIVE", "PK_D2_PA_CONSENT_OR_LIFECYCLE_DENIED")
    _require(pk.get("tenant_id") == tenant_id, "PK_D2_PK_TENANT_SCOPE_DENIED")
    observed_template = _obj(pk.get("template"), "PK_D2_PK_TEMPLATE_READBACK_MISSING")
    _require((observed_template.get("code"), observed_template.get("version"))
             == (template_name, selected_template["version"])
             and observed_template.get("status") == "ACTIVE",
             "PK_D2_PK_TEMPLATE_NOT_CURRENT")
    template_hash = _as_sha(observed_template.get("sha256"), "PK_D2_PK_TEMPLATE_HASH_INVALID")
    _require(selected_template.get("template_sha256") in (None, template_hash),
             "PK_D2_PK_TEMPLATE_HASH_CONFLICT")
    _require(observed_template.get("required_packs")
             == [{"code": code, "version": version} for code, version in sorted(mandatory)],
             "PK_D2_PK_TEMPLATE_GRAPH_MISMATCH")
    pack_rows = pk.get("packs")
    observed_packs = _identity_rows(pack_rows, code="PK_D2_PK_PACK_READBACK_INVALID")
    _require(observed_packs == desired_packs, "PK_D2_PK_PACK_VERSION_MISMATCH")
    pinned: list[dict[str, Any]] = []
    for row in sorted(pack_rows, key=lambda r: r["code"]):
        manifest = _as_sha(row.get("manifest_sha256"), "PK_D2_MANIFEST_FINGERPRINT_INVALID")
        _as_sha(row.get("certification_evidence_sha256"), "PK_D2_CERTIFICATION_EVIDENCE_REQUIRED")
        _require(row.get("status") == "ACTIVE" and row.get("certification") == "PASS"
                 and set(row.get("passed_checks") or ()) == _REQUIRED_CERTIFICATION_CHECKS,
                 "PK_D2_PACK_RETIRED_UNCERTIFIED_OR_UNVERIFIED")
        declared = next(p for p in bp["packs"] if p["code"] == row["code"])
        _require(declared.get("manifest_sha256") in (None, manifest),
                 "PK_D2_PACK_MANIFEST_CONFLICT")
        _require(declared.get("certification_evidence_ref") in
                 (None, row["certification_evidence_sha256"]),
                 "PK_D2_PACK_CERTIFICATION_CONFLICT")
        _require(country in row.get("eligible_countries", []),
                 "PK_D2_PACK_COUNTRY_INELIGIBLE")
        pinned.append({"code": row["code"], "version": row["version"],
                       "manifest_sha256": manifest,
                       "certification_evidence_sha256": row["certification_evidence_sha256"]})
    _require(pc4.get("tenant_id") == tenant_id and pc4.get("subscription_entitled") is True
             and pc4.get("finance_kernel_enabled") is True
             and pc4.get("country") == country, "PK_D2_PC4_ENTITLEMENT_DENIED")
    required_modules = _read(bp, "modules", "required")
    _require(isinstance(required_modules, list)
             and all(isinstance(item, str) and item for item in required_modules),
             "PK_D2_REQUIRED_MODULES_INVALID")
    _require(set(required_modules).issubset(set(pc4.get("effective_modules", []))),
             "PK_D2_PC4_REQUIRED_MODULE_DENIED")
    _require(pc5.get("tenant_id") == tenant_id and pc5.get("branch_id") == branch_id
             and pc5.get("active") is True and pc5.get("revoked") is False
             and pc5.get("assurance") == "A2"
             and "pack.activation_plan.preview" in pc5.get("permissions", []),
             "PK_D2_PC5_PRINCIPAL_OR_SCOPE_DENIED")
    _require(policy.get("country") == country and policy.get("tax_eligible") is True
             and policy.get("jurisdiction_eligible") is True,
             "PK_D2_COUNTRY_OR_TAX_POLICY_DENIED")
    if profile == "payments_only" or _read(bp, "channels", "provider_checkout", "required") is True:
        _require(policy.get("payment_connector_eligible") is True
                 and policy.get("provider_status") == "ADMITTED"
                 and country in policy.get("provider_countries", []),
                 "PK_D2_PROVIDER_NOT_ADMITTED")
    optional_packs: list[dict[str, Any]] = []
    if xafchat_mode == "on":
        _require(_read(bp, "channels", "xafchat", "requested") is True,
                 "PK_D2_XAFCHAT_NOT_REQUESTED")
        optional = _obj(pk.get("xafchat_optional_pack"), "PK_D2_XAFCHAT_PACK_NOT_CERTIFIED")
        _require(optional.get("status") == "ACTIVE"
                 and optional.get("certification") == "PASS"
                 and set(optional.get("passed_checks") or ()) == _REQUIRED_CERTIFICATION_CHECKS,
                 "PK_D2_XAFCHAT_PACK_NOT_CERTIFIED")
        _require(country in optional.get("eligible_countries", [])
                 and pc4.get("xafchat_entitled") is True
                 and policy.get("xafchat_connector_eligible") is True,
                 "PK_D2_XAFCHAT_CHANNEL_NOT_ELIGIBLE")
        _as_sha(optional.get("manifest_sha256"), "PK_D2_XAFCHAT_MANIFEST_REQUIRED")
        _as_sha(optional.get("certification_evidence_sha256"),
                "PK_D2_XAFCHAT_CERTIFICATION_REQUIRED")
        _require(optional.get("code") not in {row["code"] for row in pinned},
                 "PK_D2_XAFCHAT_OPTIONAL_PACK_COLLISION")
        optional_packs.append({key: optional[key] for key in
                               ("code", "version", "manifest_sha256",
                                "certification_evidence_sha256")})
        _as_version(optional["version"], "PK_D2_XAFCHAT_VERSION_INVALID")
    elif xafchat_mode == "pause":
        _require(_read(bp, "channels", "xafchat", "requested") is True,
                 "PK_D2_XAFCHAT_NOT_REQUESTED")
    basis = {
        "schema": "xcomp.ActivationPlan.v1.PK_SOURCE_PREVIEW",
        "grade": "NONOPERATIVE_LOCAL_SYNTHETIC_ONLY",
        "activation_permitted": False,
        "blueprint_id": bp["blueprint_id"],
        "revision": bp["revision"],
        "blueprint_sha256": _hash(bp),
        "tenant_id": tenant_id,
        "merchant_public_uuid": tenant["merchant_public_uuid"],
        "branch_id": branch_id,
        "profile": profile,
        "country": country,
        "pack_alias": alias,
        "template": {"code": template_name, "version": selected_template["version"],
                     "sha256": template_hash},
        "mandatory_packs": pinned,
        "optional_packs": optional_packs,
        "xafchat_mode": xafchat_mode,
        "required_modules": sorted(set(required_modules)),
        "readback_fingerprints": {p: _hash(facts[p]) for p in _PRODUCERS},
        "evaluated_at": now.isoformat(),
        "steps": [
            "PROPOSE_PK6_TEMPLATE_PLAN_ONLY",
            "REQUEST_PA_OWNER_LIFECYCLE_RECHECK",
            "REQUEST_PC1_TENANT_BRANCH_RECHECK",
            "REQUEST_PK_CERTIFICATION_RECHECK",
            "REQUEST_PC4_EFFECTIVE_ENTITLEMENT_RECHECK",
            "REQUEST_PC5_AUTHORIZED_PRINCIPAL_RECHECK",
            "REQUEST_COUNTRY_TAX_CONNECTOR_RECHECK",
            "HOLD_FOR_SEPARATELY_AUTHORIZED_D2_RELEASE",
        ],
    }
    request_sha = _hash({"bp": basis["blueprint_sha256"], "tenant": tenant_id,
                         "branch": branch_id, "rev": bp["revision"], "mode": xafchat_mode})
    if replay is not None:
        prior = _obj(replay, "PK_D2_REPLAY_INVALID")
        if prior.get("key") == _read(bp, "idempotency", "command_key"):
            _require(prior.get("request_sha256") == request_sha,
                     "PK_D2_IDEMPOTENCY_PAYLOAD_CONFLICT")
    basis["request_sha256"] = request_sha
    basis["command_key"] = _read(bp, "idempotency", "command_key")
    basis["plan_sha256"] = _hash(basis)
    return basis
