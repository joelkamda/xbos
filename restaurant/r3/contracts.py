from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class R3Error(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ChargeSourceKind(StrEnum):
    BASE_LINE = "base_line"
    MODIFIER = "modifier"


class CommercialTermKind(StrEnum):
    DISCOUNT = "discount"
    COMPLIMENTARY = "complimentary"
    CUSTOMER_SERVICE_FEE = "customer_service_fee"
    OUTPUT_TAX = "output_tax"


class EarningKind(StrEnum):
    TIP = "tip"
    COMMISSION = "commission"


class CorrectionKind(StrEnum):
    CANCEL = "cancel"
    VOID = "void"
    REVERSE = "reverse"
    REFUND = "refund"


def _money(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise R3Error("R3_INVALID_AMOUNT", f"{name} must be a finite decimal") from exc
    if not selected.is_finite() or selected < 0 or (not allow_zero and selected == 0) or selected.as_tuple().exponent < -8:
        raise R3Error("R3_INVALID_AMOUNT", f"{name} is invalid")
    return selected


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R3Error("R3_TIMEZONE_REQUIRED", f"{name} must be timezone-aware")
    return value


def _uuid(value: Any, name: str) -> UUID:
    try:
        selected = UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise R3Error("R3_IDENTITY_REQUIRED", f"{name} must be a valid UUID") from exc
    if selected.int == 0:
        raise R3Error("R3_IDENTITY_REQUIRED", f"{name} cannot be nil")
    return selected


def _currency(value: str) -> str:
    selected = str(value).strip().upper()
    if len(selected) != 3 or not selected.isalpha():
        raise R3Error("R3_INVALID_CURRENCY", selected)
    return selected


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_safe(x) for x in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise R3Error("R3_UNSUPPORTED_VALUE", type(value).__name__)


def fingerprint(value: Any) -> str:
    encoded = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChargeLine:
    order_line_public_id: UUID
    source_kind: ChargeSourceKind
    source_public_id: UUID
    description: str
    quantity: Decimal
    unit_amount: Decimal
    line_amount: Decimal
    currency_code: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_line_public_id", _uuid(self.order_line_public_id, "order_line_public_id"))
        object.__setattr__(self, "source_public_id", _uuid(self.source_public_id, "source_public_id"))
        object.__setattr__(self, "quantity", _money(self.quantity, "quantity", allow_zero=False))
        object.__setattr__(self, "unit_amount", _money(self.unit_amount, "unit_amount"))
        object.__setattr__(self, "line_amount", _money(self.line_amount, "line_amount"))
        object.__setattr__(self, "currency_code", _currency(self.currency_code))
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not self.description:
            raise R3Error("R3_CHARGE_DESCRIPTION_REQUIRED", "charge line description is required")
        if self.quantity * self.unit_amount != self.line_amount:
            raise R3Error("R3_CHARGE_ARITHMETIC", "line amount must equal quantity times unit amount")


@dataclass(frozen=True)
class CommercialTerm:
    component_public_id: UUID
    kind: CommercialTermKind
    amount: Decimal
    classification_snapshot: Mapping[str, Any]
    source_reference: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_public_id", _uuid(self.component_public_id, "component_public_id"))
        object.__setattr__(self, "amount", _money(self.amount, "commercial term amount", allow_zero=False))
        object.__setattr__(self, "classification_snapshot", dict(self.classification_snapshot))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "source_reference", str(self.source_reference).strip())
        if not self.source_reference:
            raise R3Error("R3_TERM_SOURCE_REQUIRED", "commercial term source reference is required")
        required = {
            CommercialTermKind.DISCOUNT: {"discount_reason"},
            CommercialTermKind.COMPLIMENTARY: {"complimentary_reason", "complimentary_policy"},
            CommercialTermKind.CUSTOMER_SERVICE_FEE: {"revenue_nature"},
            CommercialTermKind.OUTPUT_TAX: {"tax_jurisdiction", "tax_code"},
        }[self.kind]
        if not required.issubset(self.classification_snapshot):
            raise R3Error("R3_TERM_CLASSIFICATION_REQUIRED", self.kind.value)
        if self.kind is CommercialTermKind.COMPLIMENTARY:
            policy = str(self.classification_snapshot["complimentary_policy"].get("code", "")).strip().lower()
            if policy not in {"contra_revenue", "promotion", "service_recovery"}:
                raise R3Error("R3_COMPLIMENTARY_POLICY_INVALID", policy)


@dataclass(frozen=True)
class EarningInstruction:
    public_id: UUID
    kind: EarningKind
    amount: Decimal
    beneficiary_party_public_id: UUID | None
    policy_code: str
    source_reference: str
    basis_type: str | None = None
    basis_amount: Decimal | None = None
    rate_percent: Decimal | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", _uuid(self.public_id, "earning public_id"))
        object.__setattr__(self, "amount", _money(self.amount, "earning amount", allow_zero=False))
        object.__setattr__(self, "policy_code", str(self.policy_code).strip().lower())
        object.__setattr__(self, "source_reference", str(self.source_reference).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.beneficiary_party_public_id is not None:
            object.__setattr__(self, "beneficiary_party_public_id", _uuid(self.beneficiary_party_public_id, "beneficiary_party_public_id"))
        if not self.source_reference or not self.policy_code:
            raise R3Error("R3_EARNING_IDENTITY_REQUIRED", self.kind.value)
        if self.kind is EarningKind.TIP:
            if self.policy_code not in {"staff_beneficiary", "tenant_income"}:
                raise R3Error("R3_TIP_POLICY_INVALID", self.policy_code)
            if self.policy_code == "staff_beneficiary" and self.beneficiary_party_public_id is None:
                raise R3Error("R3_TIP_BENEFICIARY_REQUIRED", self.source_reference)
            if self.policy_code == "tenant_income" and self.beneficiary_party_public_id is not None:
                raise R3Error("R3_TIP_BENEFICIARY_FORBIDDEN", self.source_reference)
            if any(x is not None for x in (self.basis_type, self.basis_amount, self.rate_percent)):
                raise R3Error("R3_TIP_COMMISSION_FIELDS_FORBIDDEN", self.source_reference)
        else:
            if self.beneficiary_party_public_id is None:
                raise R3Error("R3_COMMISSION_BENEFICIARY_REQUIRED", self.source_reference)
            basis_type = str(self.basis_type or "").strip().lower()
            object.__setattr__(self, "basis_type", basis_type)
            if basis_type not in {"fixed", "percentage"}:
                raise R3Error("R3_COMMISSION_BASIS_INVALID", basis_type)
            if self.basis_amount is None:
                raise R3Error("R3_COMMISSION_BASIS_REQUIRED", self.source_reference)
            object.__setattr__(self, "basis_amount", _money(self.basis_amount, "commission basis", allow_zero=False))
            if basis_type == "fixed":
                if self.rate_percent is not None or self.basis_amount != self.amount:
                    raise R3Error("R3_COMMISSION_FIXED_MISMATCH", self.source_reference)
            else:
                if self.rate_percent is None:
                    raise R3Error("R3_COMMISSION_RATE_REQUIRED", self.source_reference)
                object.__setattr__(self, "rate_percent", _money(self.rate_percent, "commission rate", allow_zero=False))
                expected = self.basis_amount * self.rate_percent / Decimal("100")
                if expected != self.amount:
                    raise R3Error("R3_COMMISSION_PERCENTAGE_MISMATCH", self.source_reference)


@dataclass(frozen=True)
class RestaurantFinanceContext:
    tenant_id: int
    organization_unit_id: int
    source_type: str
    source_public_id: UUID
    merchant_party_public_id: UUID
    debtor_party_public_id: UUID | None
    currency_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    actor_service: str = "restaurant.r3"
    actor_user_id: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if min(int(self.tenant_id), int(self.organization_unit_id), int(self.calendar_policy_version)) <= 0:
            raise R3Error("R3_SCOPE_REQUIRED", "positive tenant, organization unit, and calendar policy are required")
        object.__setattr__(self, "source_public_id", _uuid(self.source_public_id, "source_public_id"))
        object.__setattr__(self, "merchant_party_public_id", _uuid(self.merchant_party_public_id, "merchant_party_public_id"))
        if self.debtor_party_public_id is not None:
            object.__setattr__(self, "debtor_party_public_id", _uuid(self.debtor_party_public_id, "debtor_party_public_id"))
        object.__setattr__(self, "currency_code", _currency(self.currency_code))
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "source_type", str(self.source_type).strip().lower())
        object.__setattr__(self, "actor_service", str(self.actor_service).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.source_type not in {"order", "tab", "tab_partition"}:
            raise R3Error("R3_SOURCE_TYPE_INVALID", self.source_type)
        if not self.actor_service:
            raise R3Error("R3_ACTOR_SERVICE_REQUIRED", self.source_type)


@dataclass(frozen=True)
class FinanceCommandDescriptor:
    sequence: int
    finance_contract: str
    command_type: str
    public_id: UUID
    idempotency_scope: str
    idempotency_key: str
    payload: Mapping[str, Any]
    economic_effects: tuple[str, ...]
    execution_allowed: bool = False
    command_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", _uuid(self.public_id, "finance descriptor public_id"))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "economic_effects", tuple(self.economic_effects))
        if self.sequence <= 0 or not self.finance_contract or not self.command_type or not self.idempotency_scope or not self.idempotency_key:
            raise R3Error("R3_DESCRIPTOR_IDENTITY_REQUIRED", self.command_type)
        if self.execution_allowed:
            raise R3Error("R3_FINANCE_EXECUTION_FORBIDDEN", self.command_type)
        object.__setattr__(self, "command_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "finance_contract": self.finance_contract,
            "command_type": self.command_type,
            "public_id": str(self.public_id),
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "payload": self.payload,
            "economic_effects": self.economic_effects,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class RestaurantFinancePlan:
    tenant_id: int
    organization_unit_id: int
    source_type: str
    source_public_id: UUID
    source_fingerprint: str
    charge_lines: tuple[ChargeLine, ...]
    terms: tuple[CommercialTerm, ...]
    earnings: tuple[EarningInstruction, ...]
    gross_sales_amount: Decimal
    customer_collectible_before_tip: Decimal
    customer_due_amount: Decimal
    commands: tuple[FinanceCommandDescriptor, ...]
    finance_authority: str = "Neutral Finance"
    writer_routing: str = "unchanged"
    execution_allowed: bool = False
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_public_id", _uuid(self.source_public_id, "source_public_id"))
        object.__setattr__(self, "charge_lines", tuple(self.charge_lines))
        object.__setattr__(self, "terms", tuple(self.terms))
        object.__setattr__(self, "earnings", tuple(self.earnings))
        object.__setattr__(self, "commands", tuple(self.commands))
        for name in ("gross_sales_amount", "customer_collectible_before_tip", "customer_due_amount"):
            object.__setattr__(self, name, _money(getattr(self, name), name))
        if not self.source_fingerprint or self.finance_authority != "Neutral Finance" or self.writer_routing != "unchanged" or self.execution_allowed:
            raise R3Error("R3_FINANCE_AUTHORITY_LEAK", str(self.source_public_id))
        if tuple(x.sequence for x in self.commands) != tuple(range(1, len(self.commands) + 1)):
            raise R3Error("R3_COMMAND_SEQUENCE_INVALID", str(self.source_public_id))
        object.__setattr__(self, "plan_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_type": self.source_type,
            "source_public_id": str(self.source_public_id),
            "source_fingerprint": self.source_fingerprint,
            "charge_lines": self.charge_lines,
            "terms": self.terms,
            "earnings": self.earnings,
            "gross_sales_amount": self.gross_sales_amount,
            "customer_collectible_before_tip": self.customer_collectible_before_tip,
            "customer_due_amount": self.customer_due_amount,
            "commands": [x.canonical_payload() for x in self.commands],
            "finance_authority": "Neutral Finance",
            "writer_routing": "unchanged",
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CorrectionRequest:
    tenant_id: int
    organization_unit_id: int
    source_public_id: UUID
    kind: CorrectionKind
    amount: Decimal
    currency_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    financial_event_exists: bool
    finalized_payment_exists: bool
    irreversible_external_effect_exists: bool
    reason_code: str
    document_number: str
    evidence_hash: str
    original_event_public_id: UUID | None = None
    original_settlement_public_id: UUID | None = None
    refund_settlement_public_id: UUID | None = None

    def __post_init__(self) -> None:
        if min(int(self.tenant_id), int(self.organization_unit_id), int(self.calendar_policy_version)) <= 0:
            raise R3Error("R3_SCOPE_REQUIRED", "correction scope is invalid")
        object.__setattr__(self, "source_public_id", _uuid(self.source_public_id, "source_public_id"))
        object.__setattr__(self, "amount", _money(self.amount, "correction amount", allow_zero=False))
        object.__setattr__(self, "currency_code", _currency(self.currency_code))
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "reason_code", str(self.reason_code).strip().lower())
        object.__setattr__(self, "document_number", str(self.document_number).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip().lower())
        if len(self.evidence_hash) != 64 or any(c not in "0123456789abcdef" for c in self.evidence_hash):
            raise R3Error("R3_EVIDENCE_HASH_REQUIRED", self.document_number)
        if not self.reason_code or not self.document_number:
            raise R3Error("R3_CORRECTION_EVIDENCE_REQUIRED", str(self.source_public_id))
        for name in ("original_event_public_id", "original_settlement_public_id", "refund_settlement_public_id"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _uuid(getattr(self, name), name))


@dataclass(frozen=True)
class CorrectionPlan:
    request_kind: CorrectionKind
    operational_disposition: str
    commands: tuple[FinanceCommandDescriptor, ...]
    original_financial_truth_immutable: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "commands", tuple(self.commands))
        if self.execution_allowed or not self.original_financial_truth_immutable:
            raise R3Error("R3_CORRECTION_AUTHORITY_LEAK", self.request_kind.value)


@dataclass(frozen=True)
class RestaurantReportRequest:
    tenant_id: int
    organization_unit_id: int
    lens: str
    start_date: date
    end_date: date
    dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "lens", str(self.lens).strip().lower())
        object.__setattr__(self, "dimensions", tuple(str(x).strip().lower() for x in self.dimensions))
        if min(int(self.tenant_id), int(self.organization_unit_id)) <= 0 or self.end_date < self.start_date:
            raise R3Error("R3_REPORT_SCOPE_INVALID", self.lens)


@dataclass(frozen=True)
class RestaurantReportPlan:
    lens: str
    finance_read_sources: tuple[str, ...]
    restaurant_dimensions: tuple[str, ...]
    financial_truth_source: str = "Neutral Finance / SO9"
    restaurant_calculates_ledger_truth: bool = False
