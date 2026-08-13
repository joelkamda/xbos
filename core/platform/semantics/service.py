"""PC3 semantic governance and deterministic lookup authority."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Protocol

from .contracts import (
    AssignClassification, ClassificationSnapshot, CreateConcept, CreateMapping,
    CreateNamespace, CreateSemanticVersion, MoveTaxonomyNode, SemanticConcept,
    SemanticMapping, SemanticNamespace, SemanticVersion, TaxonomyPlacement,
)


class SemanticAuthorityError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class SemanticRepository(Protocol):
    def create_namespace(self, command: CreateNamespace, fingerprint: str) -> SemanticNamespace: ...
    def create_concept(self, command: CreateConcept, fingerprint: str) -> SemanticConcept: ...
    def create_version(self, command: CreateSemanticVersion, fingerprint: str, definition_fingerprint: str) -> SemanticVersion: ...
    def resolve(self, qualified_code: str, effective_on: date, tenant_id: int | None = None) -> tuple[SemanticConcept, SemanticVersion] | None: ...
    def create_mapping(self, command: CreateMapping, fingerprint: str) -> SemanticMapping: ...
    def assign(self, command: AssignClassification, fingerprint: str, concept: SemanticConcept, version: SemanticVersion) -> ClassificationSnapshot: ...
    def impact(self, qualified_code: str) -> dict[str, object]: ...
    def export(self, tenant_id: int | None) -> dict[str, object]: ...
    def move_taxonomy_node(self, command: MoveTaxonomyNode) -> TaxonomyPlacement: ...


class SemanticAuthority:
    def __init__(self, repository: SemanticRepository): self.repository = repository

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _text(value: str, code: str) -> str:
        normalized=value.strip().lower()
        if not normalized: raise SemanticAuthorityError(code)
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in normalized):
            raise SemanticAuthorityError("invalid_semantic_code", value)
        return normalized

    @staticmethod
    def _required(value: str, code: str) -> str:
        normalized=value.strip().lower()
        if not normalized:raise SemanticAuthorityError(code)
        return normalized

    @staticmethod
    def _period(start: date, end: date | None) -> None:
        if end is not None and end < start: raise SemanticAuthorityError("invalid_effective_period")

    def create_namespace(self, command: CreateNamespace) -> SemanticNamespace:
        self._required(command.command_key,"missing_command_key");self._text(command.namespace_code,"missing_namespace_code");self._required(command.owner_code,"missing_owner_code")
        if command.scope.value=="tenant" and command.tenant_id is None:raise SemanticAuthorityError("tenant_namespace_requires_tenant")
        if command.scope.value!="tenant" and command.tenant_id is not None:raise SemanticAuthorityError("non_tenant_namespace_cannot_have_tenant")
        return self.repository.create_namespace(command,self._fingerprint(command.canonical_payload()))

    def create_concept(self, command: CreateConcept) -> SemanticConcept:
        self._required(command.command_key,"missing_command_key");self._text(command.namespace_code,"missing_namespace_code");self._required(command.owner_code,"missing_owner_code");self._text(command.code,"missing_concept_code")
        return self.repository.create_concept(command,self._fingerprint(command.canonical_payload()))

    def create_version(self, command: CreateSemanticVersion) -> SemanticVersion:
        self._period(command.effective_from,command.effective_to)
        if command.version_number<1:raise SemanticAuthorityError("invalid_semantic_version")
        if not command.canonical_label.strip() or not command.definition.strip():raise SemanticAuthorityError("missing_semantic_definition")
        definition_hash=hashlib.sha256(command.definition.strip().encode()).hexdigest()
        return self.repository.create_version(command,self._fingerprint(command.canonical_payload()),definition_hash)

    def resolve(self, *, qualified_code: str, effective_on: date, tenant_id: int | None = None) -> tuple[SemanticConcept,SemanticVersion]:
        if qualified_code.count(":")!=1:raise SemanticAuthorityError("invalid_qualified_semantic_code")
        result=self.repository.resolve(qualified_code.lower(),effective_on,tenant_id)
        if result is None:raise SemanticAuthorityError("semantic_reference_not_found_or_not_effective")
        return result

    def create_mapping(self, command: CreateMapping) -> SemanticMapping:
        self._period(command.effective_from,command.effective_to)
        if command.source_qualified_code.lower()==command.target_qualified_code.lower():raise SemanticAuthorityError("self_mapping_not_allowed")
        return self.repository.create_mapping(command,self._fingerprint(command.canonical_payload()))

    def assign(self, command: AssignClassification) -> ClassificationSnapshot:
        self._text(command.subject_type,"missing_subject_type")
        if not command.subject_key.strip():raise SemanticAuthorityError("missing_subject_key")
        concept,version=self.resolve(qualified_code=command.concept_qualified_code,effective_on=command.classified_on,tenant_id=command.tenant_id)
        return self.repository.assign(command,self._fingerprint(command.canonical_payload()),concept,version)

    def impact(self, qualified_code: str) -> dict[str, object]:
        return self.repository.impact(qualified_code.lower())

    def move_taxonomy_node(self, command: MoveTaxonomyNode) -> TaxonomyPlacement:
        if command.taxonomy_node_id == command.parent_id:
            raise SemanticAuthorityError("taxonomy_cycle")
        if command.expected_version < 1:
            raise SemanticAuthorityError("invalid_taxonomy_version")
        return self.repository.move_taxonomy_node(command)

    def export(self, tenant_id: int | None = None) -> bytes:
        return (json.dumps(self.repository.export(tenant_id),sort_keys=True,separators=(",",":"),default=str)+"\n").encode()
