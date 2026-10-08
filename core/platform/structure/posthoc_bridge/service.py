"""Application authority for posthoc PC1 legacy-branch structural bridging."""

from __future__ import annotations

from typing import Protocol

from core.platform.structure.contracts import LocationKind, StructuralContext, TenantLifecycle

from .contracts import (
    EnsureLegacyBranchStructuralBridge,
    LegacyBranchRecord,
    LegacyBranchStructuralBridgeResult,
    LegacyBranchStructuralMapping,
)


class PC1PosthocStructuralBridgeError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class PosthocBridgeRepository(Protocol):
    def atomic(self): ...
    def serialize(self, command: EnsureLegacyBranchStructuralBridge) -> None: ...
    def resolve_context(self, command: EnsureLegacyBranchStructuralBridge) -> StructuralContext: ...
    def mapping_by_organization(self, tenant_id: int, organization_unit_id: int) -> LegacyBranchStructuralMapping | None: ...
    def mapping_by_location(self, tenant_id: int, location_id: int) -> LegacyBranchStructuralMapping | None: ...
    def branch_by_id(self, tenant_id: int, branch_id: int) -> LegacyBranchRecord | None: ...
    def branches_by_code(self, tenant_id: int, branch_code: str) -> tuple[LegacyBranchRecord, ...]: ...
    def create_branch(self, tenant_id: int, branch_code: str, name: str) -> LegacyBranchRecord: ...
    def create_mapping(self, command: EnsureLegacyBranchStructuralBridge, branch_id: int) -> LegacyBranchStructuralMapping: ...
    def resolve_branch(self, tenant_id: int, branch_id: int) -> StructuralContext: ...


class PC1PosthocLegacyBranchStructuralBridgeAuthority:
    def __init__(self, repository: PosthocBridgeRepository):
        self.repository = repository

    def ensure(self, command: EnsureLegacyBranchStructuralBridge) -> LegacyBranchStructuralBridgeResult:
        self._validate_identity(command)
        with self.repository.atomic():
            self.repository.serialize(command)
            context = self.repository.resolve_context(command)
            self._validate_context(command, context)

            organization_mapping = self.repository.mapping_by_organization(
                command.tenant_id, command.organization_unit_id
            )
            location_mapping = self.repository.mapping_by_location(
                command.tenant_id, command.location_id
            )
            if organization_mapping is not None or location_mapping is not None:
                if (
                    organization_mapping is not None
                    and location_mapping is not None
                    and organization_mapping == location_mapping
                ):
                    branch = self.repository.branch_by_id(
                        command.tenant_id, organization_mapping.branch_id
                    )
                    if branch is None:
                        raise PC1PosthocStructuralBridgeError("mapped_legacy_branch_missing")
                    return self._result(context, branch.id, True)
                raise PC1PosthocStructuralBridgeError("incompatible_existing_structural_mapping")

            branch_code = context.location.code.strip()
            branch_name = context.location.name.strip()
            if not branch_code or not branch_name:
                raise PC1PosthocStructuralBridgeError("invalid_derived_branch_identity")
            if self.repository.branches_by_code(command.tenant_id, branch_code):
                raise PC1PosthocStructuralBridgeError("legacy_branch_code_collision")

            branch = self.repository.create_branch(command.tenant_id, branch_code, branch_name)
            self.repository.create_mapping(command, branch.id)

            resolved = self.repository.resolve_branch(command.tenant_id, branch.id)
            self._verify_result(command, context, resolved)
            return self._result(resolved, branch.id, False)

    @staticmethod
    def _validate_identity(command: EnsureLegacyBranchStructuralBridge) -> None:
        values = (command.tenant_id, command.organization_unit_id, command.location_id)
        if any(not isinstance(value, int) or value <= 0 for value in values):
            raise PC1PosthocStructuralBridgeError("invalid_structural_bridge_identity")

    @staticmethod
    def _validate_context(
        command: EnsureLegacyBranchStructuralBridge, context: StructuralContext
    ) -> None:
        if context.tenant.id != command.tenant_id or context.tenant.lifecycle is not TenantLifecycle.ACTIVE:
            raise PC1PosthocStructuralBridgeError("tenant_not_active")
        if context.organization_unit is None or context.organization_unit.id != command.organization_unit_id:
            raise PC1PosthocStructuralBridgeError("organization_context_mismatch")
        if not context.organization_unit.active:
            raise PC1PosthocStructuralBridgeError("organization_inactive")
        if context.location is None or context.location.id != command.location_id:
            raise PC1PosthocStructuralBridgeError("location_context_mismatch")
        if not context.location.active:
            raise PC1PosthocStructuralBridgeError("location_inactive")
        if context.location.kind is not LocationKind.PHYSICAL:
            raise PC1PosthocStructuralBridgeError("physical_location_required")
        if context.organization_unit.legal_entity_id != context.location.legal_entity_id:
            raise PC1PosthocStructuralBridgeError("conflicting_legal_entity_context")

    @staticmethod
    def _verify_result(
        command: EnsureLegacyBranchStructuralBridge,
        requested: StructuralContext,
        resolved: StructuralContext,
    ) -> None:
        expected_legal = requested.legal_entity.id if requested.legal_entity else None
        actual_legal = resolved.legal_entity.id if resolved.legal_entity else None
        if (
            resolved.tenant.id != command.tenant_id
            or resolved.organization_unit is None
            or resolved.organization_unit.id != command.organization_unit_id
            or resolved.location is None
            or resolved.location.id != command.location_id
            or actual_legal != expected_legal
        ):
            raise PC1PosthocStructuralBridgeError("posthoc_bridge_resolution_mismatch")

    @staticmethod
    def _result(
        context: StructuralContext, branch_id: int, replayed: bool
    ) -> LegacyBranchStructuralBridgeResult:
        return LegacyBranchStructuralBridgeResult(
            tenant_id=context.tenant.id,
            legacy_branch_id=branch_id,
            organization_unit_id=context.organization_unit.id,
            location_id=context.location.id,
            legal_entity_id=context.legal_entity.id if context.legal_entity else None,
            replayed=replayed,
        )
