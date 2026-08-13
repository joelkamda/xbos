"""Schema-neutral XA contract validators; this package owns no business truth."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping


class ExperienceContractError(ValueError):
    """A frontend-facing payload violates the XA constitution."""


class PortalKind(StrEnum):
    PLATFORM_OPERATOR = "platform_operator"
    MERCHANT_ADMIN = "merchant_admin"
    OPERATIONAL_WORKSPACE = "operational_workspace"
    POS = "pos"


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL = "approval_required"
    STEP_UP = "step_up_required"


FORBIDDEN_FRONTEND_AUTHORITIES = frozenset({
    "permissions", "financial_semantics", "party_identity", "taxonomy_semantic_identity",
    "workflow_transition_legality", "reconciliation_truth", "business_date_truth",
    "audit_truth", "entitlement_truth",
})
REQUIRED_SECTIONS = (
    "portal_context", "navigation", "configuration", "actions", "work_queue",
    "dashboard", "documents", "search", "offline", "composition",
)


def _require(value: Mapping[str, Any], fields: tuple[str, ...], where: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ExperienceContractError(f"{where}:missing={','.join(missing)}")


def _decision(value: Mapping[str, Any], where: str) -> None:
    _require(value, ("decision", "reason_code", "explanation", "source_authority"), where)
    try:
        decision = Decision(value["decision"])
    except ValueError as exc:
        raise ExperienceContractError(f"{where}:invalid_decision") from exc
    if not value["reason_code"] or not value["explanation"]:
        raise ExperienceContractError(f"{where}:unexplained_decision")
    if decision is Decision.DENY and not any(value.get(key) for key in ("missing_permission", "missing_scope", "unavailable")):
        raise ExperienceContractError(f"{where}:denial_has_no_cause")
    if decision is Decision.APPROVAL and not value.get("approval"):
        raise ExperienceContractError(f"{where}:approval_metadata_missing")
    if decision is Decision.STEP_UP and not value.get("step_up"):
        raise ExperienceContractError(f"{where}:step_up_metadata_missing")


def validate_experience(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate XA shape and cross-section authority invariants without persistence."""
    _require(payload, ("schema_version", "profile_id", *REQUIRED_SECTIONS), "experience")
    if payload["schema_version"] != "xa.frontend-experience.v1":
        raise ExperienceContractError("experience:unsupported_schema")
    context = payload["portal_context"]
    _require(context, ("portal_kind", "identity", "membership", "structural_context", "locale", "timezone", "business_date", "active_modules", "capabilities"), "portal_context")
    kind = PortalKind(context["portal_kind"])
    scope = context["structural_context"].get("scope_type")
    if kind is PortalKind.PLATFORM_OPERATOR and scope != "platform":
        raise ExperienceContractError("portal_context:platform_scope_required")
    if kind is not PortalKind.PLATFORM_OPERATOR and (scope == "platform" or not context["membership"].get("tenant_id")):
        raise ExperienceContractError("portal_context:tenant_membership_required")
    if kind is PortalKind.MERCHANT_ADMIN and context["identity"].get("platform_authority"):
        raise ExperienceContractError("portal_context:merchant_platform_authority_forbidden")

    for route in payload["navigation"]:
        _require(route, ("route_id", "path_template", "module", "visible", "permission", "entitlement", "feature_flag", "profiles", "authorization"), "navigation")
        _decision(route["authorization"], f"navigation:{route['route_id']}")
        if route.get("can_invoke") is not (route["authorization"]["decision"] == Decision.ALLOW):
            raise ExperienceContractError(f"navigation:{route['route_id']}:visibility_is_not_authorization")

    for field in payload["configuration"]:
        _require(field, ("key", "field_type", "scope", "effective_value", "value_source", "inherited", "editable", "validation", "terminology_key", "secret"), "configuration")
        if field["secret"] and (field.get("effective_value") is not None or field.get("value_exposed", False)):
            raise ExperienceContractError(f"configuration:{field['key']}:secret_value_exposed")
        if field["inherited"] and field["editable"]:
            raise ExperienceContractError(f"configuration:{field['key']}:inherited_value_editable")

    for action in payload["actions"]:
        _require(action, ("action_id", "source_authority", "from_states", "to_state", "required_permission", "approval", "step_up", "execution", "authorization"), "actions")
        _decision(action["authorization"], f"action:{action['action_id']}")
        if action["execution"].get("offline") == "queueable":
            _require(action["execution"], ("idempotency_key_required", "retry_policy", "conflict_policy"), f"action:{action['action_id']}:execution")

    for item in payload["work_queue"]:
        _require(item, ("work_item_id", "type", "priority", "assignee", "scope", "status", "due_at", "available_actions", "source_authority"), "work_queue")
    for widget in payload["dashboard"]:
        _require(widget, ("widget_id", "projection", "source_authority", "refresh", "as_of", "permission_filter", "states"), "dashboard")
        if widget["projection"] is not True or set(widget["states"]) != {"empty", "error", "stale", "ready"}:
            raise ExperienceContractError(f"dashboard:{widget['widget_id']}:projection_contract_invalid")
    for document in payload["documents"]:
        _require(document, ("document_id", "document_type", "rendering", "allowed_actions", "permission_reference", "evidence_references", "source_authority"), "documents")
    for result in payload["search"]:
        _require(result, ("result_id", "category", "tenant_id", "scope", "permitted_actions", "authorization", "source_authority"), "search")
        _decision(result["authorization"], f"search:{result['result_id']}")
        if context["membership"].get("tenant_id") and result["tenant_id"] != context["membership"]["tenant_id"]:
            raise ExperienceContractError(f"search:{result['result_id']}:cross_tenant_result")
    for operation in payload["offline"]:
        _require(operation, ("operation_id", "mode", "server_truth", "conflict_state", "retry", "idempotency"), "offline")
        if operation["mode"] == "queueable" and (not operation["idempotency"] or operation["server_truth"] == "client_defined"):
            raise ExperienceContractError(f"offline:{operation['operation_id']}:server_truth_bypass")

    composition = payload["composition"]
    _require(composition, ("template_profile_reference", "terminology", "layout_regions", "module_slots", "engine_implemented"), "composition")
    if composition["engine_implemented"]:
        raise ExperienceContractError("composition:pack_engine_forbidden_in_xa")
    claimed = set(payload.get("frontend_authorities", ()))
    if claimed & FORBIDDEN_FRONTEND_AUTHORITIES:
        raise ExperienceContractError(f"experience:frontend_authority_forbidden={sorted(claimed & FORBIDDEN_FRONTEND_AUTHORITIES)}")
    return payload
