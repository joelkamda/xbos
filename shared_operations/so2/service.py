"""SO2 application authority; Party, semantics and authorization stay external."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from .contracts import (
    ChangeRelationshipStatus,
    ClassifyRelationship,
    EstablishRelationship,
    OperationalRelationship,
    RelationshipHistory,
    RelationshipStatus,
    ScopeType,
    UpdateRelationshipPreferences,
)


class SO2AuthorityError(ValueError):
    """Stable SO0 error envelope exposed by the SO2 public boundary."""

    def __init__(self, code: str, category: str, safe_explanation: str, *, retryable: bool = False, details: dict[str, Any] | None = None):
        self.code = code
        self.category = category
        self.safe_explanation = safe_explanation
        self.retryable = retryable
        self.details = details or {}
        super().__init__(code)


class SO2Repository(Protocol):
    def establish(self, command: EstablishRelationship, party_id: int, public_id: UUID, fingerprint: str) -> OperationalRelationship: ...
    def relationship(self, tenant_id: int, public_id: UUID) -> OperationalRelationship | None: ...
    def list(self, tenant_id: int, party_public_id: UUID | None = None, relationship_type_code: str | None = None) -> tuple[OperationalRelationship, ...]: ...
    def change_status(self, command: ChangeRelationshipStatus, fingerprint: str) -> OperationalRelationship | None: ...
    def update_preferences(self, command: UpdateRelationshipPreferences, fingerprint: str) -> OperationalRelationship | None: ...
    def history(self, tenant_id: int, public_id: UUID) -> tuple[RelationshipHistory, ...]: ...
    def export(self, tenant_id: int) -> dict[str, object]: ...


_TRANSITIONS = {
    RelationshipStatus.PROSPECT: frozenset({RelationshipStatus.ACTIVE, RelationshipStatus.INACTIVE, RelationshipStatus.ENDED}),
    RelationshipStatus.ACTIVE: frozenset({RelationshipStatus.INACTIVE, RelationshipStatus.ENDED}),
    RelationshipStatus.INACTIVE: frozenset({RelationshipStatus.ACTIVE, RelationshipStatus.ENDED}),
    RelationshipStatus.ENDED: frozenset({RelationshipStatus.ACTIVE}),
}
_CANONICAL_CONTACT_KEYS = frozenset({"email", "phone", "telephone", "mobile", "postal_address", "address"})
_CONSENT_KEYS = frozenset({"consent", "marketing_consent", "opt_in", "opt_out"})


class SO2Authority:
    def __init__(
        self,
        repository: SO2Repository,
        *,
        party_resolver: Callable[[int, UUID], object | None],
        authorize: Callable[[int, str, ScopeType, int | None], bool],
        validate_scope: Callable[[int, ScopeType, int | None], bool],
        semantic_assigner: Callable[[dict[str, object]], object],
        public_id_factory: Callable[[], UUID] = uuid4,
    ):
        self.repository = repository
        self.party_resolver = party_resolver
        self.authorize = authorize
        self.validate_scope = validate_scope
        self.semantic_assigner = semantic_assigner
        self.public_id_factory = public_id_factory

    @staticmethod
    def _fingerprint(command: object) -> str:
        payload = asdict(command)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _code(value: str, field: str) -> str:
        code = value.strip().lower()
        if not code or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in code):
            raise SO2AuthorityError(f"SO2_INVALID_{field.upper()}", "validation_failure", f"{field} must be a non-empty neutral code")
        return code

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise SO2AuthorityError(f"SO2_INVALID_{field.upper()}", "validation_failure", f"{field} is required")
        return normalized

    def _permit(self, tenant_id: int, permission: str, scope_type: ScopeType = ScopeType.TENANT, scope_id: int | None = None) -> None:
        if not self.authorize(tenant_id, permission, scope_type, scope_id):
            raise SO2AuthorityError("SO2_PERMISSION_DENIED", "permission_denied", "The requested CRM operation is not permitted")

    def _get(self, tenant_id: int, public_id: UUID) -> OperationalRelationship:
        relationship = self.repository.relationship(tenant_id, public_id)
        if relationship is None:
            raise SO2AuthorityError("SO2_NOT_FOUND", "not_found", "The operational relationship was not found in this tenant")
        return relationship

    @staticmethod
    def _preferences(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise SO2AuthorityError("SO2_INVALID_PREFERENCES", "validation_failure", "Preferences must be an object")
        forbidden = {str(key).casefold() for key in value} & (_CANONICAL_CONTACT_KEYS | _CONSENT_KEYS)
        if forbidden:
            raise SO2AuthorityError("SO2_PREFERENCE_AUTHORITY_VIOLATION", "validation_failure", "Canonical contacts and consent are not SO2 preference values", details={"keys": sorted(forbidden)})
        try:
            json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise SO2AuthorityError("SO2_INVALID_PREFERENCES", "validation_failure", "Preferences must be JSON-safe") from exc
        return value

    def establish(self, command: EstablishRelationship) -> OperationalRelationship:
        self._permit(command.tenant_id, "crm.relationship.establish")
        relationship_type = self._code(command.relationship_type_code, "relationship_type")
        self._required(command.command_key, "command_key")
        if command.initial_status not in {RelationshipStatus.PROSPECT, RelationshipStatus.ACTIVE}:
            raise SO2AuthorityError("SO2_INVALID_INITIAL_STATUS", "invalid_state_transition", "A relationship starts as prospect or active")
        party = self.party_resolver(command.tenant_id, command.party_public_id)
        if party is None or getattr(party, "tenant_id", None) != command.tenant_id or getattr(party, "public_id", None) is None or UUID(str(party.public_id)) != command.party_public_id:
            raise SO2AuthorityError("SO2_PARTY_NOT_FOUND", "scope_mismatch", "The PC2 Party was not found in this tenant")
        scope_type, scope_id = ScopeType.TENANT, None
        if command.location_id is not None:
            scope_type, scope_id = ScopeType.LOCATION, command.location_id
        elif command.organization_unit_id is not None:
            scope_type, scope_id = ScopeType.ORGANIZATION_UNIT, command.organization_unit_id
        if not self.validate_scope(command.tenant_id, scope_type, scope_id):
            raise SO2AuthorityError("SO2_SCOPE_MISMATCH", "scope_mismatch", "The structural scope does not belong to this tenant")
        normalized = EstablishRelationship(
            command.command_key, command.tenant_id, command.party_public_id, relationship_type,
            command.initial_status, command.effective_from, self._code(command.source_code, "source") if command.source_code else None,
            command.purpose.strip() if command.purpose else None, self._preferences(command.preferences or {}),
            command.organization_unit_id, command.location_id,
        )
        return self.repository.establish(normalized, int(getattr(party, "id")), self.public_id_factory(), self._fingerprint(normalized))

    def relationship(self, tenant_id: int, public_id: UUID) -> OperationalRelationship:
        self._permit(tenant_id, "crm.relationship.read")
        return self._get(tenant_id, public_id)

    def list_relationships(self, tenant_id: int, *, party_public_id: UUID | None = None, relationship_type_code: str | None = None) -> tuple[OperationalRelationship, ...]:
        self._permit(tenant_id, "crm.relationship.read")
        return self.repository.list(tenant_id, party_public_id, self._code(relationship_type_code, "relationship_type") if relationship_type_code else None)

    def change_status(self, command: ChangeRelationshipStatus) -> OperationalRelationship:
        self._permit(command.tenant_id, "crm.relationship.lifecycle")
        self._required(command.command_key, "command_key")
        current = self._get(command.tenant_id, command.relationship_public_id)
        if command.to_status not in _TRANSITIONS[current.status]:
            raise SO2AuthorityError("SO2_INVALID_STATE_TRANSITION", "invalid_state_transition", "The requested relationship transition is not allowed")
        normalized = ChangeRelationshipStatus(command.command_key, command.tenant_id, command.relationship_public_id, command.expected_version, command.to_status, self._code(command.reason_code, "reason"), command.occurred_at)
        result = self.repository.change_status(normalized, self._fingerprint(normalized))
        if result is None:
            raise SO2AuthorityError("SO2_STALE_VERSION", "stale_version", "The relationship changed; reload before retrying")
        return result

    def end(self, command_key: str, tenant_id: int, public_id: UUID, expected_version: int, reason_code: str, occurred_at) -> OperationalRelationship:
        return self.change_status(ChangeRelationshipStatus(command_key, tenant_id, public_id, expected_version, RelationshipStatus.ENDED, reason_code, occurred_at))

    def reactivate(self, command_key: str, tenant_id: int, public_id: UUID, expected_version: int, reason_code: str, occurred_at) -> OperationalRelationship:
        return self.change_status(ChangeRelationshipStatus(command_key, tenant_id, public_id, expected_version, RelationshipStatus.ACTIVE, reason_code, occurred_at))

    def update_preferences(self, command: UpdateRelationshipPreferences) -> OperationalRelationship:
        self._permit(command.tenant_id, "crm.relationship.preference.manage")
        self._required(command.command_key, "command_key")
        self._get(command.tenant_id, command.relationship_public_id)
        normalized = UpdateRelationshipPreferences(command.command_key, command.tenant_id, command.relationship_public_id, command.expected_version, self._preferences(command.preferences))
        result = self.repository.update_preferences(normalized, self._fingerprint(normalized))
        if result is None:
            raise SO2AuthorityError("SO2_STALE_VERSION", "stale_version", "The relationship changed; reload before retrying")
        return result

    def classify(self, command: ClassifyRelationship) -> object:
        self._permit(command.tenant_id, "crm.relationship.classify")
        self._required(command.command_key, "command_key")
        relationship = self._get(command.tenant_id, command.relationship_public_id)
        return self.semantic_assigner({
            "command_key": command.command_key,
            "tenant_id": command.tenant_id,
            "subject_type": "so2_operational_relationship",
            "subject_key": str(relationship.public_id),
            "concept_qualified_code": command.concept_qualified_code,
            "classified_on": date.fromisoformat(command.classified_on.date().isoformat()),
        })

    def history(self, tenant_id: int, public_id: UUID) -> tuple[RelationshipHistory, ...]:
        self._permit(tenant_id, "crm.relationship.read")
        self._get(tenant_id, public_id)
        return self.repository.history(tenant_id, public_id)

    def export(self, tenant_id: int) -> bytes:
        self._permit(tenant_id, "crm.relationship.export")
        return (json.dumps(self.repository.export(tenant_id), sort_keys=True, separators=(",", ":"), default=str) + "\n").encode()
