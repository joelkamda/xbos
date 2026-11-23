"""G4-A canonical merchant-product publication seam; no synthetic authority.

This application service is deliberately NOT routed in canonical startup.
It calls the EXISTING canonical PC5, PC3, PK, and SO1 authorities. The supplied
transaction port is responsible for row locking and atomic source/version CAS.
Without a Finance mapping, effective pack/semantic, or real PC5 decision it
fails closed. No R7 v3r_* / v24_* tables, static tenant or fake permissions.

A production adapter requires separately accepted migrations, audit provenance,
and a single trustworthy transaction/version source. Unit tests use an explicit
TEST repository; those tests do not commission a real PC5 issuer.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID

from core.platform.security_authority.contracts import (
    AuthorizationRequest, Decision, ScopeType, StructuralScope,
)
from core.platform.security_authority.service import SecurityAuthority
from core.platform.semantics.contracts import SemanticLifecycle
from core.platform.semantics.service import SemanticAuthority
from pack_platform.contracts import PackKind, PackStatus, PackVersionRecord
from pack_platform.service import PackAuthority
from shared_operations.so1.contracts import AtomicUnit
from shared_operations.so1.service import SO1Authority

PUBLISH_PERMISSION = "restaurant.product.publish"
ZONES = ("MAIN", "VIP", "BAR")


class CanonicalProductError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ProductState(StrEnum):
    REVIEW = "review"
    PUBLISHED = "published"


@dataclass(frozen=True)
class ZonePriceDraft:
    zone: str
    amount_xaf: int
    row_version: int


@dataclass(frozen=True)
class ProductReviewSnapshot:
    public_id: UUID
    tenant_id: int
    location_id: int
    creator_identity_id: int
    atomic_unit_public_id: UUID
    atomic_unit_version: int
    semantic_qualified_code: str
    semantic_version: int
    pack_code: str
    pack_version: str
    revision: int
    status: ProductState
    prices: tuple[ZonePriceDraft, ...]


@dataclass(frozen=True)
class FinanceAccountBinding:
    tenant_id: int
    location_id: int
    atomic_unit_public_id: UUID
    revenue_account_ref: str
    inventory_account_ref: str
    cogs_account_ref: str
    tax_policy_ref: str
    row_version: int
    certified: bool


@dataclass(frozen=True)
class CanonicalPublish:
    tenant_id: int
    location_id: int
    product_public_id: UUID
    session_id: UUID
    expected_revision: int
    expected_price_revisions: tuple[int, int, int]
    occurred_at: datetime
    correlation_id: str


@dataclass(frozen=True)
class CanonicalPublishProof:
    tenant_id: int
    location_id: int
    product_public_id: UUID
    committed_revision: int
    reviewer_identity_id: int
    pc3_semantic_version: int
    pack_manifest_sha256: str
    so1_atomic_unit_version: int
    finance_binding_version: int
    price_revisions: tuple[int, int, int]
    official_finance_posted: bool = False
    payments_executed: bool = False


class LockedProductTransaction(Protocol):
    def load_for_update(self, tenant_id: int, location_id: int,
                        product_public_id: UUID) -> ProductReviewSnapshot | None: ...
    def publish_cas(self, *, snapshot: ProductReviewSnapshot,
                    reviewer_identity_id: int, expected_revision: int,
                    expected_price_revisions: tuple[int, int, int],
                    pack_manifest_sha256: str,
                    pc3_semantic_version: int,
                    so1_atomic_unit_version: int,
                    finance_binding_version: int,
                    correlation_id: str) -> CanonicalPublishProof | None: ...


class CanonicalProductStore(Protocol):
    def transaction(self) -> AbstractContextManager[LockedProductTransaction]: ...


class CanonicalProductPublisher:
    def __init__(self, *, security: SecurityAuthority, semantics: SemanticAuthority,
                 packs: PackAuthority, so1: SO1Authority,
                 pack_version: Callable[[str, str], PackVersionRecord | None],
                 finance_binding: Callable[[int, int, UUID], FinanceAccountBinding | None],
                 store: CanonicalProductStore):
        if (not isinstance(security, SecurityAuthority)
                or not isinstance(semantics, SemanticAuthority)
                or not isinstance(packs, PackAuthority)
                or not isinstance(so1, SO1Authority)):
            raise CanonicalProductError("G4A_CANONICAL_AUTHORITY_IMPLEMENTATIONS_REQUIRED")
        self.security, self.semantics, self.packs, self.so1 = (
            security, semantics, packs, so1)
        self.pack_version, self.finance_binding, self.store = (
            pack_version, finance_binding, store)

    def publish(self, command: CanonicalPublish) -> CanonicalPublishProof:
        if (not isinstance(command, CanonicalPublish)
                or type(command.tenant_id) is not int or command.tenant_id < 1
                or type(command.location_id) is not int or command.location_id < 1
                or not isinstance(command.product_public_id, UUID)
                or command.product_public_id.int == 0
                or not isinstance(command.session_id, UUID)
                or command.session_id.int == 0
                or type(command.expected_revision) is not int
                or command.expected_revision < 1
                or not isinstance(command.expected_price_revisions, tuple)
                or len(command.expected_price_revisions) != 3
                or any(type(v) is not int or v < 1
                       for v in command.expected_price_revisions)
                or not isinstance(command.occurred_at, datetime)
                or command.occurred_at.utcoffset() is None
                or not isinstance(command.correlation_id, str)
                or not 3 <= len(command.correlation_id.strip()) <= 128):
            raise CanonicalProductError("G4A_PUBLISH_COMMAND_INVALID")
        at = command.occurred_at.astimezone(timezone.utc)
        try:
            with self.store.transaction() as tx:
                product = tx.load_for_update(
                    command.tenant_id, command.location_id,
                    command.product_public_id)
                if not isinstance(product, ProductReviewSnapshot):
                    raise CanonicalProductError("G4A_PRODUCT_SCOPE_NOT_FOUND")
                if (product.tenant_id != command.tenant_id
                        or product.location_id != command.location_id
                        or product.public_id != command.product_public_id):
                    raise CanonicalProductError("G4A_PRODUCT_SCOPE_MISMATCH")
                if (product.status is not ProductState.REVIEW
                        or product.revision != command.expected_revision):
                    raise CanonicalProductError("G4A_SOURCE_REVISION_OR_STATE_STALE")
                if (len(product.prices) != 3
                        or tuple(p.zone for p in product.prices) != ZONES
                        or any(type(p.amount_xaf) is not int or p.amount_xaf < 0
                               or type(p.row_version) is not int or p.row_version < 1
                               for p in product.prices)
                        or tuple(p.row_version for p in product.prices)
                        != command.expected_price_revisions):
                    raise CanonicalProductError("G4A_PRICE_REVISION_OR_FORMAT_STALE")
                decision = self.security.authorize(AuthorizationRequest(
                    session_id=command.session_id,
                    permission_code=PUBLISH_PERMISSION,
                    tenant_id=command.tenant_id,
                    target_scope=StructuralScope(ScopeType.LOCATION,
                                                 command.location_id),
                    resource_type="restaurant_product",
                    resource_id=str(product.public_id),
                    occurred_at=at,
                    correlation_id=command.correlation_id,
                ))
                if decision.decision is not Decision.ALLOW or (
                    type(decision.identity_id) is not int or
                    decision.identity_id <= 0 or
                    decision.tenant_id != command.tenant_id):
                    raise CanonicalProductError("G4A_REAL_PC5_DENIED_OR_NOT_ADMITTED")
                if decision.identity_id == product.creator_identity_id:
                    raise CanonicalProductError("G4A_INDEPENDENT_REVIEWER_REQUIRED")
                pack = self.packs.state(command.tenant_id, product.pack_code)
                if (pack is None or pack.tenant_id != command.tenant_id
                        or pack.pack_code != product.pack_code
                        or pack.version != product.pack_version
                        or pack.status is not PackStatus.ACTIVE
                        or type(pack.row_version) is not int
                        or pack.row_version < 1):
                    raise CanonicalProductError("G4A_CANONICAL_PACK_NOT_ACTIVE")
                version = self.pack_version(product.pack_code, product.pack_version)
                if (not isinstance(version, PackVersionRecord)
                        or version.pack_code != product.pack_code
                        or version.version != product.pack_version
                        or version.kind is not PackKind.INDUSTRY
                        or not isinstance(version.manifest_sha256, str)
                        or len(version.manifest_sha256) != 64
                        or any(c not in "0123456789abcdef" for c in version.manifest_sha256)):
                    raise CanonicalProductError("G4A_PACK_MANIFEST_VERSION_NOT_VERIFIED")
                concept, semantic_version = self.semantics.resolve(
                    qualified_code=product.semantic_qualified_code,
                    effective_on=at.date(),
                    tenant_id=command.tenant_id,
                )
                if (concept.qualified_code != product.semantic_qualified_code
                        or concept.lifecycle is not SemanticLifecycle.ACTIVE
                        or semantic_version.concept_id != concept.id
                        or semantic_version.version_number != product.semantic_version
                        or semantic_version.effective_from > at.date()
                        or semantic_version.effective_to is not None
                            and semantic_version.effective_to < at.date()):
                    raise CanonicalProductError("G4A_PC3_CLASSIFICATION_NOT_EFFECTIVE")
                unit = self.so1.atomic_unit(command.tenant_id,
                                             product.atomic_unit_public_id)
                if (not isinstance(unit, AtomicUnit)
                        or unit.tenant_id != command.tenant_id
                        or unit.public_id != product.atomic_unit_public_id
                        or not unit.active
                        or unit.row_version != product.atomic_unit_version):
                    raise CanonicalProductError("G4A_SO1_ATOMIC_UNIT_STALE")
                finance = self.finance_binding(
                    command.tenant_id, command.location_id,
                    product.atomic_unit_public_id)
                if (not isinstance(finance, FinanceAccountBinding)
                        or finance.tenant_id != command.tenant_id
                        or finance.location_id != command.location_id
                        or finance.atomic_unit_public_id != product.atomic_unit_public_id
                        or not finance.certified
                        or type(finance.row_version) is not int
                        or finance.row_version < 1
                        or not all(isinstance(x, str) and x.strip()
                                   for x in (
                                     finance.revenue_account_ref,
                                     finance.inventory_account_ref,
                                     finance.cogs_account_ref,
                                     finance.tax_policy_ref,
                                   ))):
                    raise CanonicalProductError("G4A_FINANCE_ACCOUNT_MAPPING_NOT_CERTIFIED")
                proof = tx.publish_cas(
                    snapshot=product,
                    reviewer_identity_id=decision.identity_id,
                    expected_revision=command.expected_revision,
                    expected_price_revisions=command.expected_price_revisions,
                    pack_manifest_sha256=version.manifest_sha256,
                    pc3_semantic_version=semantic_version.version_number,
                    so1_atomic_unit_version=unit.row_version,
                    finance_binding_version=finance.row_version,
                    correlation_id=command.correlation_id)
                if (not isinstance(proof, CanonicalPublishProof)
                        or proof.tenant_id != command.tenant_id
                        or proof.location_id != command.location_id
                        or proof.product_public_id != command.product_public_id
                        or proof.committed_revision != command.expected_revision + 1
                        or proof.reviewer_identity_id != decision.identity_id
                        or proof.price_revisions != command.expected_price_revisions
                        or proof.official_finance_posted or proof.payments_executed):
                    raise CanonicalProductError("G4A_CANONICAL_ATOMIC_PUBLICATION_FAILED")
                return proof
        except CanonicalProductError:
            raise
        except Exception as exc:
            raise CanonicalProductError("G4A_CANONICAL_AUTHORITY_OR_TRANSACTION_UNAVAILABLE") from exc
