"""PC5 fail-closed identity, authorization, approval, and audit authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

from .contracts import *


class SecurityAuthorityError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SecurityAuthorityError("timezone_required")
    return value.astimezone(timezone.utc)


def _code(value: str, name: str, *, namespaced: bool = False) -> str:
    selected = str(value or "").strip().lower()
    pattern = r"[a-z][a-z0-9_-]{1,63}(?:\.[a-z][a-z0-9_-]{0,63}){2,3}" if namespaced else r"[a-z][a-z0-9_.-]{1,159}"
    if not re.fullmatch(pattern, selected):
        raise SecurityAuthorityError(f"invalid_{name}")
    return selected


def _fingerprint(value) -> str:
    def default(item):
        if is_dataclass(item): return asdict(item)
        if isinstance(item, (date, datetime, time)): return item.isoformat()
        if isinstance(item, Enum): return item.value
        return str(item)
    return hashlib.sha256(json.dumps(value, default=default, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _safe_metadata(value: dict | None) -> dict:
    value = value or {}
    serialized = json.dumps(value, sort_keys=True, default=str).lower()
    forbidden = ("password", "password_hash", "token", "secret", "credential", "authorization")
    if any(marker in serialized for marker in forbidden):
        raise SecurityAuthorityError("audit_sensitive_material_forbidden")
    return value


class SecurityAuthority:
    """Canonical PC5 service boundary; repository performs persistence and locking."""

    def __init__(self, repository):
        self.repository = repository

    def create_identity(self, *, command_key: str, login_name: str, party_id: int | None = None):
        login = str(login_name or "").strip().casefold()
        if not login or len(login) > 254:
            raise SecurityAuthorityError("invalid_login_identity")
        return self.repository.create_identity(command_key, _fingerprint((login, party_id)), login, party_id)

    def add_membership(self, *, command_key: str, identity_id: int, tenant_id: int, valid_from: datetime, valid_to: datetime | None = None, party_id: int | None = None):
        start = _aware(valid_from); end = _aware(valid_to) if valid_to else None
        if end and end <= start: raise SecurityAuthorityError("invalid_membership_period")
        return self.repository.add_membership(command_key, _fingerprint((identity_id, tenant_id, start, end, party_id)), identity_id, tenant_id, start, end, party_id)

    def register_permission(self, *, command_key: str, definition: PermissionDefinition):
        code = _code(definition.code, "permission_code", namespaced=True)
        normalized = PermissionDefinition(code, _code(definition.owner_module, "owner_module"), _code(definition.resource, "resource"), _code(definition.action, "action"), _code(definition.risk_class, "risk_class"), tuple(definition.allowed_scopes), int(definition.required_assurance), _code(definition.approval_profile, "approval_profile") if definition.approval_profile else None)
        if not normalized.allowed_scopes or normalized.required_assurance not in range(1, 5):
            raise SecurityAuthorityError("invalid_permission_definition")
        return self.repository.register_permission(command_key, _fingerprint(normalized), normalized)

    def create_role(self, *, command_key: str, role_code: str, tenant_id: int | None, permissions: tuple[str, ...]):
        role = _code(role_code, "role_code")
        selected = tuple(sorted({_code(x, "permission_code", namespaced=True) for x in permissions}))
        if any(self.repository.permission(code) is None for code in selected):
            raise SecurityAuthorityError("unknown_permission")
        return self.repository.create_role(command_key, _fingerprint((role, tenant_id, selected)), role, tenant_id, selected)

    def assign_role(self, *, command_key: str, assignment: RoleAssignment):
        self._scope(assignment.tenant_id, assignment.scope)
        start = _aware(assignment.valid_from); end = _aware(assignment.valid_to) if assignment.valid_to else None
        if end and end <= start: raise SecurityAuthorityError("invalid_role_assignment_period")
        normalized = RoleAssignment(assignment.identity_id, assignment.tenant_id, _code(assignment.role_code, "role_code"), assignment.scope, start, end, assignment.actor_type)
        return self.repository.assign_role(command_key, _fingerprint(normalized), normalized)

    def create_session(self, *, command_key: str, identity_id: int, tenant_id: int | None, actor_type: ActorType, assurance_level: int, authenticated_at: datetime, expires_at: datetime, device_identity_id: int | None = None):
        start = _aware(authenticated_at); end = _aware(expires_at)
        if end <= start or assurance_level not in range(1, 5): raise SecurityAuthorityError("invalid_session")
        return self.repository.create_session(command_key, _fingerprint((identity_id, tenant_id, actor_type, assurance_level, start, end, device_identity_id)), identity_id, tenant_id, actor_type, assurance_level, start, end, device_identity_id)

    def revoke_session(self, session_id, revoked_at: datetime):
        return self.repository.revoke_session(session_id, _aware(revoked_at))

    def revoke_membership(self, *, identity_id: int, tenant_id: int, revoked_at: datetime):
        return self.repository.revoke_membership(identity_id, tenant_id, _aware(revoked_at))

    def grant_step_up(self, *, command_key: str, session_id, assurance_level: int, expires_at: datetime, scope: StructuralScope | None = None):
        end = _aware(expires_at)
        if assurance_level not in range(2, 5): raise SecurityAuthorityError("invalid_step_up_grant")
        return self.repository.grant_step_up(command_key, _fingerprint((session_id, assurance_level, end, scope)), session_id, assurance_level, end, scope)

    def register_service_identity(self, *, command_key: str, service_code: str, owner_module: str, tenant_id: int | None, credential_reference: str):
        code = _code(service_code, "service_code"); owner = _code(owner_module, "owner_module"); reference = _code(credential_reference, "credential_reference")
        return self.repository.register_service_identity(command_key, _fingerprint((code, owner, tenant_id, reference)), code, owner, tenant_id, reference)

    def register_device_identity(self, *, command_key: str, device_code: str, tenant_id: int, location_id: int | None, organization_unit_id: int | None, assurance_level: int = 1):
        code = _code(device_code, "device_code")
        if assurance_level not in range(1, 5): raise SecurityAuthorityError("invalid_device_assurance")
        return self.repository.register_device_identity(command_key, _fingerprint((code, tenant_id, location_id, organization_unit_id, assurance_level)), code, tenant_id, location_id, organization_unit_id, assurance_level)

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        at = _aware(request.occurred_at)
        permission_code = _code(request.permission_code, "permission_code", namespaced=True)
        permission = self.repository.permission(permission_code)
        if permission is None:
            return self._deny(permission_code, "unknown_permission", request.tenant_id)
        session = self.repository.session(request.session_id)
        if session is None or session.revoked_at or session.expires_at <= at:
            return self._deny(permission_code, "session_inactive", request.tenant_id)
        delegated = session.tenant_id is None and request.tenant_id is not None and self.repository.delegation_active(request.delegation_id, session.identity_id, request.tenant_id, permission_code, request.target_scope, at)
        if session.tenant_id != request.tenant_id and not delegated:
            return self._deny(permission_code, "session_tenant_mismatch", request.tenant_id, session.identity_id)
        if session.actor_type is ActorType.HUMAN and request.tenant_id is not None and not delegated and not self.repository.membership_active(session.identity_id, request.tenant_id, at):
            return self._deny(permission_code, "membership_inactive", request.tenant_id, session.identity_id)
        if session.actor_type is not ActorType.HUMAN and not self.repository.principal_active(session.actor_type, session.identity_id, request.tenant_id):
            return self._deny(permission_code, "principal_inactive", request.tenant_id, session.identity_id)
        if not all((request.module_available, request.module_enabled, request.entitled, request.feature_active)):
            return self._deny(permission_code, "pc4_capability_unavailable", request.tenant_id, session.identity_id)
        if request.target_scope.scope_type not in permission.allowed_scopes:
            return self._deny(permission_code, "scope_type_not_permitted", request.tenant_id, session.identity_id)
        self._scope(request.tenant_id, request.target_scope)
        assignments = self.repository.assignments(session.identity_id, request.tenant_id, at, session.actor_type) if not delegated else ()
        if not delegated and not any(permission_code in item["permissions"] and self._scope_matches(item["scope"], request.target_scope, request.attributes or {}) for item in assignments):
            return self._deny(permission_code, "permission_not_established", request.tenant_id, session.identity_id)
        policy = self.repository.policy(permission_code, request.tenant_id, at)
        required_assurance = max(permission.required_assurance, int((policy or {}).get("required_assurance", 1)))
        effective_assurance = max(session.assurance_level, self.repository.step_up_assurance(request.session_id, request.target_scope, at))
        if effective_assurance < required_assurance:
            return AuthorizationDecision(Decision.REQUIRE_STEP_UP, permission_code, "insufficient_assurance", session.identity_id, request.tenant_id, required_assurance, permission.approval_profile)
        approval_profile = (policy or {}).get("approval_profile") or permission.approval_profile
        if approval_profile and not self.repository.approval_satisfied(request.approval_id, request, session.identity_id, at):
            return AuthorizationDecision(Decision.REQUIRE_APPROVAL, permission_code, "independent_approval_required", session.identity_id, request.tenant_id, required_assurance, approval_profile)
        return AuthorizationDecision(Decision.ALLOW, permission_code, "authority_established", session.identity_id, request.tenant_id, required_assurance, approval_profile, request.correlation_id)

    def grant_support_access(self, grant: SupportAccessGrant):
        start=_aware(grant.effective_from);end=_aware(grant.expires_at);reason=str(grant.reason or "").strip()
        self._scope(grant.tenant_id,grant.scope)
        if end<=start or end-start>timedelta(hours=8) or not reason or grant.approval_id is None:raise SecurityAuthorityError("invalid_support_access_grant")
        normalized=SupportAccessGrant(grant.public_id,grant.operator_identity_id,grant.tenant_id,_code(grant.permission_code,"permission_code",namespaced=True),grant.scope,start,end,reason,grant.approval_id,grant.break_glass)
        return self.repository.grant_support_access(normalized,_fingerprint(normalized))

    def revoke_support_access(self, public_id, revoked_at: datetime):return self.repository.revoke_support_access(public_id,_aware(revoked_at))

    def request_approval(self, request: ApprovalRequest):
        self._scope(request.tenant_id, request.scope)
        if request.required_approvals < 1:
            raise SecurityAuthorityError("invalid_approval_request")
        return self.repository.request_approval(request, _fingerprint(request))

    def decide_approval(self, decision: ApprovalDecision):
        normalized = ApprovalDecision(decision.approval_id, decision.approver_identity_id, decision.approved, _aware(decision.decided_at), str(decision.reason).strip())
        if not normalized.reason: raise SecurityAuthorityError("approval_reason_required")
        return self.repository.decide_approval(normalized, _fingerprint(normalized))

    def append_audit(self, envelope: AuditEnvelope):
        self._scope(envelope.tenant_id, envelope.scope or StructuralScope(ScopeType.PLATFORM if envelope.tenant_id is None else ScopeType.TENANT, envelope.tenant_id))
        normalized = AuditEnvelope(**{**envelope.__dict__, "occurred_at": _aware(envelope.occurred_at), "action_code": _code(envelope.action_code, "audit_action"), "source_module": _code(envelope.source_module, "source_module"), "metadata": _safe_metadata(envelope.metadata)})
        return self.repository.append_audit(normalized, _fingerprint(normalized))

    def query_audit(self, query: AuditQuery):
        if _aware(query.end) <= _aware(query.start): raise SecurityAuthorityError("invalid_audit_query_period")
        decision = self.authorize(AuthorizationRequest(query.requester_session_id, "pc5.audit.evidence.query", query.tenant_id, query.scope or StructuralScope(ScopeType.TENANT, query.tenant_id), "audit_evidence", "query", _aware(query.start)))
        if decision.decision is not Decision.ALLOW: raise SecurityAuthorityError("audit_query_forbidden")
        return self.repository.query_audit(query)

    def export_identity(self, identity_id: int):
        result = self.repository.export_identity(identity_id)
        result["credential_material_included"] = False
        result["session_secrets_included"] = False
        return result

    @staticmethod
    def _deny(code, reason, tenant, identity=None):
        return AuthorizationDecision(Decision.DENY, code, reason, identity, tenant)

    @staticmethod
    def _scope(tenant_id: int | None, scope: StructuralScope):
        if scope.scope_type is ScopeType.PLATFORM:
            if tenant_id is not None or scope.scope_id is not None: raise SecurityAuthorityError("invalid_platform_scope")
        elif tenant_id is None: raise SecurityAuthorityError("tenant_scope_required")
        elif scope.scope_type is ScopeType.TENANT and scope.scope_id != tenant_id: raise SecurityAuthorityError("tenant_scope_id_mismatch")
        elif scope.scope_id is None: raise SecurityAuthorityError("structural_scope_id_required")

    @staticmethod
    def _scope_matches(assigned: StructuralScope, target: StructuralScope, attributes: dict) -> bool:
        if assigned == target: return True
        if assigned.scope_type is ScopeType.TENANT and target.scope_type is not ScopeType.PLATFORM: return True
        ancestors = attributes.get("scope_ancestors", {})
        return assigned.scope_type.value in ancestors and ancestors[assigned.scope_type.value] == assigned.scope_id
