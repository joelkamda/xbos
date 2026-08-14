"""SO1 application authority; persistence is supplied through a private port."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable, Protocol
from uuid import UUID

from .contracts import (
    AtomicUnit, Catalog, CreateAtomicUnit, CreateCatalog, CreateOffer, DefinePrice,
    Offer, Price, PublishCatalogEntry, ResolvePrice, UpdateAtomicUnit, UpdateOffer,
)


class SO1AuthorityError(RuntimeError):
    def __init__(self, code: str, safe_explanation: str):
        self.code = code; self.safe_explanation = safe_explanation
        super().__init__(f"{code}: {safe_explanation}")


class SO1Repository(Protocol):
    def create_atomic_unit(self, command: CreateAtomicUnit, public_id: UUID) -> AtomicUnit: ...
    def atomic_unit(self, tenant_id: int, public_id: UUID) -> AtomicUnit | None: ...
    def update_atomic_unit(self, command: UpdateAtomicUnit) -> AtomicUnit | None: ...
    def deactivate_atomic_unit(self, tenant_id: int, public_id: UUID, expected_version: int) -> AtomicUnit | None: ...
    def link_taxonomy(self, tenant_id: int, atomic_unit_public_id: UUID, taxonomy_node_id: int) -> None: ...
    def create_catalog(self, command: CreateCatalog, public_id: UUID) -> Catalog: ...
    def catalog(self, tenant_id: int, public_id: UUID) -> Catalog | None: ...
    def publish_entry(self, command: PublishCatalogEntry, public_id: UUID) -> UUID: ...
    def create_offer(self, command: CreateOffer, public_id: UUID) -> Offer: ...
    def offer(self, tenant_id: int, public_id: UUID) -> Offer | None: ...
    def update_offer(self, command: UpdateOffer) -> Offer | None: ...
    def deactivate_offer(self, tenant_id: int, public_id: UUID, expected_version: int) -> Offer | None: ...
    def define_price(self, command: DefinePrice, public_id: UUID) -> Price: ...
    def price(self, tenant_id: int, public_id: UUID) -> Price | None: ...
    def deactivate_price(self, tenant_id: int, public_id: UUID, expected_version: int) -> Price | None: ...
    def resolve_price(self, query: ResolvePrice) -> Price | None: ...


class SO1Authority:
    def __init__(self, repository: SO1Repository, *, authorize: Callable[[str, int, str, int | None], bool], validate_scope: Callable[[int, str, int | None], bool], public_id_factory: Callable[[], UUID]):
        self._repository = repository; self._authorize = authorize
        self._validate_scope = validate_scope; self._public_id = public_id_factory

    def _guard(self, permission: str, tenant_id: int, scope_type: str = "tenant", scope_id: int | None = None) -> None:
        if tenant_id <= 0 or not self._validate_scope(tenant_id, scope_type, scope_id):
            raise SO1AuthorityError("SO1_SCOPE_MISMATCH", "The requested structural scope is unavailable.")
        if not self._authorize(permission, tenant_id, scope_type, scope_id):
            raise SO1AuthorityError("SO1_PERMISSION_DENIED", "The requested operation is not authorized.")

    def create_atomic_unit(self, command: CreateAtomicUnit) -> AtomicUnit:
        self._guard("so1.atomic_unit.create", command.tenant_id)
        if not command.code.strip() or not command.name.strip():
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Code and name are required.")
        return self._repository.create_atomic_unit(command, self._public_id())

    def atomic_unit(self, tenant_id: int, public_id: UUID) -> AtomicUnit:
        self._guard("so1.atomic_unit.read", tenant_id)
        result = self._repository.atomic_unit(tenant_id, public_id)
        if result is None: raise SO1AuthorityError("SO1_NOT_FOUND", "Atomic Unit was not found in this tenant.")
        return result

    def update_atomic_unit(self, command: UpdateAtomicUnit) -> AtomicUnit:
        self._guard("so1.atomic_unit.update", command.tenant_id)
        result = self._repository.update_atomic_unit(command)
        if result is None: raise SO1AuthorityError("SO1_STALE_VERSION", "Atomic Unit version is stale or unavailable.")
        return result

    def deactivate_atomic_unit(self, tenant_id: int, public_id: UUID, expected_version: int) -> AtomicUnit:
        self._guard("so1.atomic_unit.deactivate", tenant_id)
        result = self._repository.deactivate_atomic_unit(tenant_id, public_id, expected_version)
        if result is None: raise SO1AuthorityError("SO1_STALE_VERSION", "Atomic Unit version is stale or unavailable.")
        return result

    def classify_atomic_unit(self, tenant_id: int, public_id: UUID, taxonomy_node_id: int, semantic_assign: Callable[[int, str, str], Any]) -> None:
        self._guard("so1.atomic_unit.classify", tenant_id)
        unit = self.atomic_unit(tenant_id, public_id)
        semantic_assign(tenant_id, "atomic_unit", str(unit.id))
        self._repository.link_taxonomy(tenant_id, public_id, taxonomy_node_id)

    def create_catalog(self, command: CreateCatalog) -> Catalog:
        self._guard("so1.catalog.manage", command.tenant_id, command.scope_type, command.scope_id)
        if command.effective_to is not None and command.effective_to <= command.effective_from:
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Catalog effective window is invalid.")
        return self._repository.create_catalog(command, self._public_id())

    def catalog(self, tenant_id: int, public_id: UUID) -> Catalog:
        self._guard("so1.catalog.read", tenant_id)
        result = self._repository.catalog(tenant_id, public_id)
        if result is None: raise SO1AuthorityError("SO1_NOT_FOUND", "Catalog was not found in this tenant.")
        return result

    def publish_catalog_entry(self, command: PublishCatalogEntry) -> UUID:
        self._guard("so1.catalog.manage", command.tenant_id)
        return self._repository.publish_entry(command, self._public_id())

    def create_offer(self, command: CreateOffer) -> Offer:
        self._guard("so1.offer.manage", command.tenant_id)
        if not command.components or any(component.quantity <= 0 for component in command.components):
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Offer composition requires positive components.")
        ordered = tuple(sorted(command.components, key=lambda item: (item.sequence, str(item.atomic_unit_public_id))))
        return self._repository.create_offer(replace(command, components=ordered), self._public_id())

    def offer(self, tenant_id: int, public_id: UUID) -> Offer:
        self._guard("so1.offer.read", tenant_id)
        result = self._repository.offer(tenant_id, public_id)
        if result is None: raise SO1AuthorityError("SO1_NOT_FOUND", "Offer was not found in this tenant.")
        return result

    def update_offer(self, command: UpdateOffer) -> Offer:
        self._guard("so1.offer.manage", command.tenant_id)
        if not command.components or any(component.quantity <= 0 for component in command.components):
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Offer composition requires positive components.")
        ordered=tuple(sorted(command.components,key=lambda item:(item.sequence,str(item.atomic_unit_public_id))))
        result=self._repository.update_offer(replace(command,components=ordered))
        if result is None:raise SO1AuthorityError("SO1_STALE_VERSION", "Offer version is stale or unavailable.")
        return result

    def deactivate_offer(self, tenant_id: int, public_id: UUID, expected_version: int) -> Offer:
        self._guard("so1.offer.manage", tenant_id)
        result = self._repository.deactivate_offer(tenant_id, public_id, expected_version)
        if result is None: raise SO1AuthorityError("SO1_STALE_VERSION", "Offer version is stale or unavailable.")
        return result

    def define_price(self, command: DefinePrice) -> Price:
        self._guard("so1.price.manage", command.tenant_id, command.scope_type, command.scope_id)
        if command.amount < Decimal("0") or len(command.currency) != 3 or command.currency != command.currency.upper():
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Price amount or currency is invalid.")
        if command.effective_to is not None and command.effective_to <= command.effective_from:
            raise SO1AuthorityError("SO1_VALIDATION_FAILURE", "Price effective window is invalid.")
        return self._repository.define_price(command, self._public_id())

    def resolve_price(self, query: ResolvePrice) -> Price:
        self._guard("so1.price.read", query.tenant_id, query.scope_type, query.scope_id)
        result = self._repository.resolve_price(query)
        if result is None: raise SO1AuthorityError("SO1_PRICE_UNAVAILABLE", "No effective price is available.")
        return result

    def price(self, tenant_id: int, public_id: UUID) -> Price:
        self._guard("so1.price.read",tenant_id)
        result=self._repository.price(tenant_id,public_id)
        if result is None:raise SO1AuthorityError("SO1_NOT_FOUND", "Price was not found in this tenant.")
        return result

    def deactivate_price(self, tenant_id: int, public_id: UUID, expected_version: int) -> Price:
        self._guard("so1.price.manage", tenant_id)
        result = self._repository.deactivate_price(tenant_id, public_id, expected_version)
        if result is None: raise SO1AuthorityError("SO1_STALE_VERSION", "Price version is stale or unavailable.")
        return result
