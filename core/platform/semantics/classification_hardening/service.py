"""Global-capable semantic-classification authority layered on frozen PC3."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol
from uuid import UUID

from core.platform.semantics import SemanticAuthorityError

from .contracts import (
    AssignSemanticClassification,
    ClassificationRecord,
    ClassificationView,
    ClearTenantTaxonomyOverlay,
    CreateTaxonomyNode,
    CreateTaxonomySystem,
    EffectiveTaxonomyNode,
    EndSemanticClassification,
    HealthIssue,
    HealthSeverity,
    ReparentTaxonomyNode,
    SemanticSource,
    SemanticTaxonomyNode,
    SetTenantTaxonomyOverlay,
    TargetTypeDefinition,
    TaxonomyPlacementVersion,
    TaxonomySystemDefinition,
    TenantTaxonomyOverlay,
)


_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class SemanticClassificationRepository(Protocol):
    def create_system(self, command: CreateTaxonomySystem, fingerprint: str) -> TaxonomySystemDefinition: ...
    def create_node(self, command: CreateTaxonomyNode, fingerprint: str) -> tuple[SemanticTaxonomyNode, TaxonomyPlacementVersion]: ...
    def reparent_node(self, command: ReparentTaxonomyNode, fingerprint: str) -> TaxonomyPlacementVersion: ...
    def set_overlay(self, command: SetTenantTaxonomyOverlay, fingerprint: str) -> TenantTaxonomyOverlay: ...
    def clear_overlay(self, command: ClearTenantTaxonomyOverlay, fingerprint: str) -> None: ...
    def assign(self, command: AssignSemanticClassification, fingerprint: str) -> ClassificationRecord: ...
    def end_assignment(self, command: EndSemanticClassification, fingerprint: str) -> ClassificationRecord: ...
    def hierarchy_rows(self, system_code: str, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> list[dict]: ...
    def classification_rows(self, tenant_id: int, target_type: str, target_key: str, effective_at: datetime, active_sources: tuple[str, ...]) -> list[dict]: ...
    def graph_rows(self, node_public_id: UUID, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> dict[str, object]: ...
    def health_rows(self, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> list[HealthIssue]: ...


class ClassificationTargetRegistry:
    """Owning-authority validators for classifiable target types.

    PC3 never performs dynamic SQL against arbitrary caller-supplied tables. Each
    target type must be registered by composition with an owner and validator.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, TargetTypeDefinition] = {}
        self._validators: dict[str, Callable[[int, str], bool]] = {}

    def register(self, definition: TargetTypeDefinition, validator: Callable[[int, str], bool]) -> None:
        code = definition.target_type.strip().lower()
        if not _CODE.fullmatch(code):
            raise SemanticAuthorityError("invalid_classification_target_type", code)
        if code in self._definitions:
            raise SemanticAuthorityError("duplicate_classification_target_type", code)
        self._definitions[code] = definition
        self._validators[code] = validator

    def validate(self, tenant_id: int, target_type: str, target_key: str) -> TargetTypeDefinition:
        code = target_type.strip().lower()
        definition = self._definitions.get(code)
        if definition is None:
            raise SemanticAuthorityError("unknown_classification_target_type", code)
        if not target_key.strip():
            raise SemanticAuthorityError("missing_classification_target_key")
        if not self._validators[code](tenant_id, target_key.strip()):
            raise SemanticAuthorityError("classification_target_not_found_or_cross_tenant")
        return definition

    def definitions(self) -> tuple[TargetTypeDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


class SemanticClassificationAuthority:
    def __init__(self, repository: SemanticClassificationRepository, targets: ClassificationTargetRegistry):
        self.repository = repository
        self.targets = targets

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _code(value: str, code: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise SemanticAuthorityError(code)
        if not _CODE.fullmatch(normalized):
            raise SemanticAuthorityError("invalid_semantic_code", value)
        return normalized

    @staticmethod
    def _required(value: str, code: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise SemanticAuthorityError(code)
        return normalized

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise SemanticAuthorityError("semantic_time_requires_timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _source(command) -> None:
        if not command.source_key.strip():
            raise SemanticAuthorityError("semantic_source_requires_key")
        if command.provenance is not None and not isinstance(command.provenance, dict):
            raise SemanticAuthorityError("semantic_provenance_must_be_object")

    @classmethod
    def _taxonomy_source(cls, command) -> None:
        cls._source(command)
        if command.source_type is SemanticSource.TEMPLATE:
            raise SemanticAuthorityError("template_cannot_author_taxonomy_placement")
        if command.tenant_id is None and command.source_type is SemanticSource.TENANT:
            raise SemanticAuthorityError("tenant_source_requires_tenant_taxonomy_node")
        if command.tenant_id is not None and command.source_type not in {SemanticSource.TENANT, SemanticSource.MIGRATION}:
            raise SemanticAuthorityError("tenant_taxonomy_node_requires_tenant_or_migration_source")

    @classmethod
    def _overlay_source(cls, command) -> None:
        cls._source(command)
        if command.source_type not in {SemanticSource.PACK, SemanticSource.TENANT, SemanticSource.TEMPLATE, SemanticSource.MIGRATION}:
            raise SemanticAuthorityError("invalid_tenant_taxonomy_overlay_source")

    def create_taxonomy_system(self, command: CreateTaxonomySystem) -> TaxonomySystemDefinition:
        self._required(command.command_key, "missing_command_key")
        self._code(command.system_code, "missing_taxonomy_system_code")
        self._code(command.namespace_code, "missing_namespace_code")
        self._required(command.owner_code, "missing_owner_code")
        return self.repository.create_system(command, self._fingerprint(command.canonical_payload()))

    def create_taxonomy_node(self, command: CreateTaxonomyNode) -> tuple[SemanticTaxonomyNode, TaxonomyPlacementVersion]:
        self._required(command.command_key, "missing_command_key")
        self._code(command.system_code, "missing_taxonomy_system_code")
        self._code(command.node_code, "missing_taxonomy_node_code")
        if command.concept_qualified_code.count(":") != 1:
            raise SemanticAuthorityError("invalid_qualified_semantic_code")
        self._aware(command.effective_from)
        self._taxonomy_source(command)
        return self.repository.create_node(command, self._fingerprint(command.canonical_payload()))

    def reparent_taxonomy_node(self, command: ReparentTaxonomyNode) -> TaxonomyPlacementVersion:
        self._required(command.command_key, "missing_command_key")
        if command.expected_placement_version < 1:
            raise SemanticAuthorityError("invalid_taxonomy_placement_version")
        if command.parent_node_public_id == command.node_public_id:
            raise SemanticAuthorityError("taxonomy_cycle")
        self._aware(command.effective_from)
        self._taxonomy_source(command)
        return self.repository.reparent_node(command, self._fingerprint(command.canonical_payload()))

    def set_tenant_overlay(self, command: SetTenantTaxonomyOverlay) -> TenantTaxonomyOverlay:
        self._required(command.command_key, "missing_command_key")
        if command.tenant_id <= 0:
            raise SemanticAuthorityError("invalid_tenant")
        if command.expected_overlay_version is not None and command.expected_overlay_version < 1:
            raise SemanticAuthorityError("invalid_taxonomy_overlay_version")
        if command.parent_override_public_id is not None and not command.has_parent_override:
            raise SemanticAuthorityError("taxonomy_parent_override_requires_explicit_flag")
        if command.parent_override_public_id == command.node_public_id:
            raise SemanticAuthorityError("taxonomy_cycle")
        if command.local_label is not None and not command.local_label.strip():
            raise SemanticAuthorityError("empty_local_taxonomy_label")
        self._aware(command.effective_from)
        self._overlay_source(command)
        return self.repository.set_overlay(command, self._fingerprint(command.canonical_payload()))

    def clear_tenant_overlay(self, command: ClearTenantTaxonomyOverlay) -> None:
        self._required(command.command_key, "missing_command_key")
        if command.expected_overlay_version < 1:
            raise SemanticAuthorityError("invalid_taxonomy_overlay_version")
        self._aware(command.effective_from)
        self.repository.clear_overlay(command, self._fingerprint(command.canonical_payload()))

    def assign(self, command: AssignSemanticClassification) -> ClassificationRecord:
        self._required(command.command_key, "missing_command_key")
        self._code(command.target_type, "missing_classification_target_type")
        self._required(command.target_key, "missing_classification_target_key")
        if command.concept_qualified_code.count(":") != 1:
            raise SemanticAuthorityError("invalid_qualified_semantic_code")
        self._aware(command.classified_at)
        self._source(command)
        self.targets.validate(command.tenant_id, command.target_type, command.target_key)
        return self.repository.assign(command, self._fingerprint(command.canonical_payload()))

    def end_classification(self, command: EndSemanticClassification) -> ClassificationRecord:
        self._required(command.command_key, "missing_command_key")
        self._aware(command.expected_effective_from)
        self._aware(command.effective_to)
        if command.effective_to <= command.expected_effective_from:
            raise SemanticAuthorityError("invalid_classification_effective_period")
        return self.repository.end_assignment(command, self._fingerprint(command.canonical_payload()))

    def hierarchy(self, *, system_code: str, effective_at: datetime, tenant_id: int | None = None, active_sources: Iterable[str] = ()) -> tuple[EffectiveTaxonomyNode, ...]:
        self._code(system_code, "missing_taxonomy_system_code")
        at = self._aware(effective_at)
        rows = self.repository.hierarchy_rows(system_code.lower(), at, tenant_id, tuple(sorted(set(active_sources))))
        by_id = {row["node_public_id"]: row for row in rows}
        cache: dict[UUID, tuple[int, tuple[str, ...]]] = {}

        def lineage(node_id: UUID, seen: frozenset[UUID] = frozenset()) -> tuple[int, tuple[str, ...]]:
            if node_id in cache:
                return cache[node_id]
            if node_id in seen:
                raise SemanticAuthorityError("taxonomy_cycle")
            row = by_id[node_id]
            parent = row["parent_public_id"]
            if parent is None:
                result = (0, (row["label"],))
            elif parent not in by_id:
                result = (0, (row["label"],))
            else:
                depth, path = lineage(parent, seen | {node_id})
                result = (depth + 1, path + (row["label"],))
            cache[node_id] = result
            return result

        result = []
        for row in rows:
            depth, path = lineage(row["node_public_id"])
            result.append(EffectiveTaxonomyNode(**row, depth=depth, path=path))
        result.sort(key=lambda item: (item.path, item.sort_order, str(item.node_public_id)))
        return tuple(result)

    def classifications(self, *, tenant_id: int, target_type: str, target_key: str, effective_at: datetime, active_sources: Iterable[str] = ()) -> tuple[ClassificationView, ...]:
        self.targets.validate(tenant_id, target_type, target_key)
        at = self._aware(effective_at)
        rows = self.repository.classification_rows(tenant_id, target_type.lower(), target_key, at, tuple(sorted(set(active_sources))))
        systems = sorted({row["system_code"] for row in rows if row["system_code"]})
        paths: dict[UUID, tuple[str, ...]] = {}
        for system in systems:
            for node in self.hierarchy(system_code=system, effective_at=at, tenant_id=tenant_id, active_sources=active_sources):
                paths[node.node_public_id] = node.path
        result = []
        for row in rows:
            materialized = dict(row)
            node_id = materialized["node_public_id"]
            if node_id is not None and node_id not in paths:
                # The semantic assignment remains explainable, but an inactive pack/template
                # placement must not leak into the tenant's effective taxonomy or matrix.
                materialized["system_code"] = None
                materialized["node_public_id"] = None
                materialized["node_code"] = None
                path = (materialized["label"],)
            else:
                path = paths.get(node_id, (materialized["label"],))
            result.append(ClassificationView(**materialized, path=path))
        return tuple(result)

    def matrix(self, *, tenant_id: int, targets: Iterable[tuple[str, str]], system_codes: Iterable[str], effective_at: datetime, active_sources: Iterable[str] = ()) -> dict[str, dict[str, tuple[str, ...]]]:
        wanted = {self._code(code, "missing_taxonomy_system_code") for code in system_codes}
        matrix: dict[str, dict[str, tuple[str, ...]]] = {}
        for target_type, target_key in targets:
            key = f"{target_type.lower()}:{target_key}"
            cells: dict[str, list[str]] = {system: [] for system in sorted(wanted)}
            for item in self.classifications(tenant_id=tenant_id, target_type=target_type, target_key=target_key, effective_at=effective_at, active_sources=active_sources):
                if item.system_code in wanted:
                    cells[item.system_code].append(" / ".join(item.path))
            matrix[key] = {system: tuple(sorted(values)) for system, values in cells.items()}
        return matrix

    def graph(self, *, node_public_id: UUID, effective_at: datetime, tenant_id: int | None = None, active_sources: Iterable[str] = ()) -> dict[str, object]:
        return self.repository.graph_rows(node_public_id, self._aware(effective_at), tenant_id, tuple(sorted(set(active_sources))))

    def health(self, *, effective_at: datetime, tenant_id: int | None = None, active_sources: Iterable[str] = ()) -> tuple[HealthIssue, ...]:
        at = self._aware(effective_at)
        issues = list(self.repository.health_rows(at, tenant_id, tuple(sorted(set(active_sources)))))
        # Effective parent visibility depends on active pack/template sources and is therefore
        # checked at the read-model boundary, not by global database constraints.
        systems = sorted({row.system_code for row in self._all_visible_nodes(at, tenant_id, active_sources)})
        for system in systems:
            nodes = self.hierarchy(system_code=system, effective_at=at, tenant_id=tenant_id, active_sources=active_sources)
            visible = {node.node_public_id for node in nodes}
            for node in nodes:
                if node.parent_public_id is not None and node.parent_public_id not in visible:
                    issues.append(HealthIssue(
                        severity=HealthSeverity.ERROR,
                        code="effective_parent_not_visible",
                        object_type="semantic_taxonomy_node",
                        object_key=str(node.node_public_id),
                        system_code=system,
                        detail="Effective parent is not visible under the tenant/source composition.",
                        remediation="Enable the contributing source or re-parent the node through governed taxonomy placement.",
                    ))
        return tuple(sorted(issues, key=lambda x: (x.severity.value, x.code, x.object_type, x.object_key)))

    def _all_visible_nodes(self, effective_at: datetime, tenant_id: int | None, active_sources: Iterable[str]) -> tuple[EffectiveTaxonomyNode, ...]:
        systems = self.repository.graph_rows(UUID(int=0), effective_at, tenant_id, tuple(sorted(set(active_sources)))).get("systems", ())
        result: list[EffectiveTaxonomyNode] = []
        for system in systems:
            result.extend(self.hierarchy(system_code=str(system), effective_at=effective_at, tenant_id=tenant_id, active_sources=active_sources))
        return tuple(result)
