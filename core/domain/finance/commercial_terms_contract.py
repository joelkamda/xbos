"""Typed M5.2 commercial price, allowance, fee, and tax contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID


CONTRACT_CODE = "XBOS_M52_COMMERCIAL_TERMS_TAXES_AND_FEES"
CONTRACT_VERSION = 1
COMPONENT_TYPES = frozenset({"discount", "complimentary", "customer_service_fee", "output_tax"})
COMPLIMENTARY_PROFILES = frozenset({
    "complimentary_contra_revenue", "complimentary_promotion", "complimentary_service_recovery"
})


class CommercialTermsError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _money(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommercialTermsError("invalid_amount", f"{field_name} must be a finite decimal") from exc
    if not selected.is_finite() or selected < 0 or (positive and selected <= 0):
        raise CommercialTermsError("invalid_amount", f"{field_name} has an invalid amount")
    return selected


@dataclass(frozen=True)
class CommercialTermComponent:
    public_id: UUID
    source_record_id: int
    component_type: str
    amount: Decimal
    classification_snapshot: Mapping[str, Any]
    posting_profile_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "component_type", str(self.component_type).strip().lower())
        object.__setattr__(self, "amount", _money(self.amount, "component amount", positive=True))
        if self.public_id.int == 0 or int(self.source_record_id) <= 0:
            raise CommercialTermsError("component_identity_required", "component identity and source authority are required")
        if self.component_type not in COMPONENT_TYPES:
            if self.component_type == "provider_fee":
                raise CommercialTermsError("provider_fee_authority", "provider fees remain under the M4.6 provider-financial authority")
            raise CommercialTermsError("unsupported_component_type", "commercial component type is not supported")
        if not isinstance(self.classification_snapshot, Mapping) or not isinstance(self.metadata, Mapping):
            raise CommercialTermsError("invalid_metadata", "classification and metadata must be objects")
        required = {
            "discount": {"discount_reason"},
            "complimentary": {"complimentary_reason", "complimentary_policy"},
            "customer_service_fee": {"revenue_nature"},
            "output_tax": {"tax_jurisdiction", "tax_code"},
        }[self.component_type]
        if not required.issubset(self.classification_snapshot):
            raise CommercialTermsError("classification_required", "component classification is incomplete")
        expected = {
            "discount": "discount_contra_revenue",
            "customer_service_fee": "commercial_recognition",
            "output_tax": "output_tax_recognition",
        }.get(self.component_type)
        if self.component_type == "complimentary":
            policy = str(self.classification_snapshot["complimentary_policy"].get("code", ""))
            expected = {
                "contra_revenue": "complimentary_contra_revenue",
                "promotion": "complimentary_promotion",
                "service_recovery": "complimentary_service_recovery",
            }.get(policy)
            if expected is None:
                raise CommercialTermsError("complimentary_policy_invalid", "complimentary policy is not approved")
        selected = self.posting_profile_code or expected
        if selected != expected:
            raise CommercialTermsError("posting_profile_mismatch", "posting profile does not match component policy")
        object.__setattr__(self, "posting_profile_code", selected)
        object.__setattr__(self, "classification_snapshot", dict(self.classification_snapshot))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class RecognizeCommercialTermsCommand:
    tenant_id: int
    organization_unit_id: int
    gross_sales_amount: Decimal
    customer_collectible_amount: Decimal
    currency_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    idempotency_scope: str
    actor_service: str
    components: tuple[CommercialTermComponent, ...]
    actor_user_id: int | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "gross_sales_amount", _money(self.gross_sales_amount, "gross sales amount"))
        object.__setattr__(self, "customer_collectible_amount", _money(self.customer_collectible_amount, "customer collectible amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        object.__setattr__(self, "components", tuple(self.components))
        if min(int(self.tenant_id), int(self.organization_unit_id), int(self.calendar_policy_version)) <= 0:
            raise CommercialTermsError("scope_required", "positive tenant, organization, and calendar policy are required")
        if not self.components:
            raise CommercialTermsError("components_required", "at least one commercial component is required")
        if len({item.public_id for item in self.components}) != len(self.components) or len({item.source_record_id for item in self.components}) != len(self.components):
            raise CommercialTermsError("duplicate_component", "component and source identities must be unique")
        reductions = sum((item.amount for item in self.components if item.component_type in {"discount", "complimentary"}), Decimal("0"))
        additions = sum((item.amount for item in self.components if item.component_type in {"customer_service_fee", "output_tax"}), Decimal("0"))
        if reductions > self.gross_sales_amount:
            raise CommercialTermsError("allowance_capacity_exceeded", "discount and complimentary value exceed gross sales")
        if self.customer_collectible_amount != self.gross_sales_amount - reductions + additions:
            raise CommercialTermsError("collectible_mismatch", "customer collectible does not reconcile to governed commercial terms")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CommercialTermsError("timezone_required", "occurred_at must be timezone-aware")
        if not self.currency_code or not str(self.idempotency_scope).strip() or not str(self.actor_service).strip():
            raise CommercialTermsError("command_identity_required", "currency, idempotency scope, and actor service are required")
