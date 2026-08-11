"""Deterministic M7.1 mappings from legacy WND snapshots to command plans."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from .wnd_finance_adapter_contract import LegacyFinancialEnvelope
from .wnd_financial_mapping_contract import (
    CanonicalCommandDescriptor,
    CanonicalMappingPlan,
    WndFinancialMappingError,
    money,
    require_hash,
)

_NAMESPACE = uuid5(NAMESPACE_URL, "xbos:m71:wnd-financial-mapping:v1")


def _text(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name, "")).strip()
    if not value:
        raise WndFinancialMappingError("required_field_missing", name)
    return value


def _uuid(payload: Mapping[str, Any], name: str) -> str:
    try:
        value = UUID(_text(payload, name))
    except (ValueError, AttributeError) as exc:
        raise WndFinancialMappingError("invalid_uuid", name) from exc
    if value.int == 0:
        raise WndFinancialMappingError("invalid_uuid", name)
    return str(value)


def _currency(payload: Mapping[str, Any]) -> str:
    value = _text(payload, "currency_code").upper()
    if len(value) != 3 or not value.isalpha():
        raise WndFinancialMappingError("invalid_currency", value)
    return value


class WndFinancialMappingService:
    @classmethod
    def map(cls, envelope: LegacyFinancialEnvelope) -> CanonicalMappingPlan:
        kind = str(envelope.payload.get("kind", "")).strip().lower()
        expected = {
            "commercial_sale": "commercial",
            "payment_settlement": "payment",
            "receivable_repayment": "receivable",
            "refund": "adjustment",
        }.get(kind)
        if expected is None:
            raise WndFinancialMappingError("unsupported_mapping_kind", kind)
        if envelope.source_family.value != expected:
            raise WndFinancialMappingError("source_family_mismatch", f"{envelope.source_family.value}:{kind}")
        correlation = envelope.correlation_id or uuid5(_NAMESPACE, f"{envelope.tenant_id}:{envelope.source_identity}:correlation")
        commands = getattr(cls, f"_map_{kind}")(envelope, correlation)
        return CanonicalMappingPlan(
            tenant_id=envelope.tenant_id,
            organization_unit_id=envelope.organization_unit_id,
            source_identity=envelope.source_identity,
            source_fingerprint=envelope.payload_fingerprint,
            mapping_kind=kind,
            correlation_id=correlation,
            commands=commands,
        )

    @classmethod
    def _descriptor(
        cls,
        envelope: LegacyFinancialEnvelope,
        sequence: int,
        contract_code: str,
        command_type: str,
        payload: Mapping[str, Any],
        effects: tuple[str, ...],
    ) -> CanonicalCommandDescriptor:
        source_key = f"{envelope.tenant_id}:{envelope.organization_unit_id}:{envelope.source_identity}:{command_type}:{sequence}"
        public_id = uuid5(_NAMESPACE, source_key)
        scope = f"m71.{envelope.payload['kind']}"
        return CanonicalCommandDescriptor(
            sequence=sequence,
            contract_code=contract_code,
            command_type=command_type,
            public_id=public_id,
            idempotency_scope=scope,
            idempotency_key=f"{scope}:{envelope.source_identity}:{sequence}",
            payload={
                **payload,
                "tenant_id": envelope.tenant_id,
                "organization_unit_id": envelope.organization_unit_id,
                "source_component": "wnd_finance_adapter",
                "source_record_id": envelope.source_record_id,
                "business_date": envelope.business_date,
                "occurred_at": envelope.source_updated_at,
                "source_payload_fingerprint": envelope.payload_fingerprint,
            },
            economic_effects=effects,
        )

    @classmethod
    def _map_commercial_sale(cls, envelope: LegacyFinancialEnvelope, correlation: UUID):
        source = envelope.payload
        gross = money(source.get("gross_amount"), "gross_amount", allow_zero=False)
        discount = money(source.get("discount_amount", 0), "discount_amount")
        complimentary = money(source.get("complimentary_amount", 0), "complimentary_amount")
        collected = money(source.get("collected_amount", 0), "collected_amount")
        unpaid = money(source.get("unpaid_amount", 0), "unpaid_amount")
        if discount + complimentary > gross:
            raise WndFinancialMappingError("allowance_capacity_exceeded", envelope.source_identity)
        collectible = gross - discount - complimentary
        if collected + unpaid != collectible:
            raise WndFinancialMappingError("commercial_totals_mismatch", envelope.source_identity)
        currency = _currency(source)
        revenue_nature = _text(source, "revenue_nature")
        commands = [cls._descriptor(
            envelope, 1, "XBOS_CANONICAL_FINANCIAL_EVENT_ENGINE", "CanonicalFinancialEventCommand",
            {
                "event_type_code": "COMMERCIAL_REVENUE_RECOGNIZED", "event_version": 1,
                "amount": gross, "currency_code": currency, "economic_role": "recognition",
                "classification_snapshot": {"revenue_nature": {"code": revenue_nature}},
                "posting_profile_code": "commercial_recognition", "correlation_id": correlation,
            },
            ("revenue_recognition", "receivable_control_increase"),
        )]
        components = []
        if discount:
            components.append({
                "component_type": "discount", "amount": discount,
                "classification_snapshot": {"discount_reason": {"code": _text(source, "discount_reason")}},
                "posting_profile_code": "discount_contra_revenue",
            })
        if complimentary:
            policy = _text(source, "complimentary_policy").lower()
            profiles = {
                "contra_revenue": "complimentary_contra_revenue",
                "promotion": "complimentary_promotion",
                "service_recovery": "complimentary_service_recovery",
            }
            if policy not in profiles:
                raise WndFinancialMappingError("complimentary_policy_invalid", policy)
            components.append({
                "component_type": "complimentary", "amount": complimentary,
                "classification_snapshot": {
                    "complimentary_reason": {"code": _text(source, "complimentary_reason")},
                    "complimentary_policy": {"code": policy},
                },
                "posting_profile_code": profiles[policy],
            })
        if components:
            commands.append(cls._descriptor(
                envelope, len(commands) + 1, "XBOS_M52_COMMERCIAL_TERMS_TAXES_AND_FEES", "RecognizeCommercialTermsCommand",
                {"gross_sales_amount": gross, "customer_collectible_amount": collectible, "currency_code": currency,
                 "components": components, "correlation_id": correlation},
                tuple("discount_or_complimentary_recognition" for _ in components),
            ))
        if unpaid:
            commands.append(cls._descriptor(
                envelope, len(commands) + 1, "XBOS_M50_RECEIVABLES_AND_CUSTOMER_BALANCES", "OpenReceivableCommand",
                {"obligation_type": "trade_receivable", "original_amount": unpaid, "currency_code": currency,
                 "party_reference": source.get("customer_reference"), "correlation_id": correlation},
                ("receivable_opened",),
            ))
        return tuple(commands)

    @classmethod
    def _settlement_descriptors(cls, envelope: LegacyFinancialEnvelope, correlation: UUID, *, allocation: bool):
        source = envelope.payload
        amount = money(source.get("amount"), "amount", allow_zero=False)
        fee = money(source.get("fee_amount", 0), "fee_amount")
        if fee > amount:
            raise WndFinancialMappingError("settlement_fee_exceeds_amount", envelope.source_identity)
        method = _text(source, "payment_method_code").lower()
        rail = _text(source, "payment_rail_code").lower()
        finality = _text(source, "finality_status").lower()
        evidence_hash = require_hash(source.get("evidence_hash"))
        evidence_verified = source.get("evidence_verified") is True
        if finality != "final" or not evidence_verified:
            raise WndFinancialMappingError("verified_finality_required", envelope.source_identity)
        external = str(source.get("external_settlement_reference") or "").strip()
        if method != "cash" and not external:
            raise WndFinancialMappingError("external_settlement_identity_required", envelope.source_identity)
        currency = _currency(source)
        intent_id = str(uuid5(_NAMESPACE, f"{envelope.tenant_id}:{envelope.source_identity}:intent"))
        settlement_id = str(uuid5(_NAMESPACE, f"{envelope.tenant_id}:{envelope.source_identity}:settlement"))
        commands = [cls._descriptor(
            envelope, 1, "XBOS_M41_TYPED_PAYMENT_REQUEST_AND_INTENT_COMMANDS", "CreatePaymentIntentCommand",
            {"canonical_public_id": intent_id, "requested_amount": amount, "currency_code": currency,
             "payment_method_policy": {"allowed_methods": [method], "allow_mixed_tender": False, "max_tenders": 1},
             "correlation_id": correlation},
            ("payment_intent_control",),
        ), cls._descriptor(
            envelope, 2, "XBOS_M43_TRANSACTIONAL_PAYMENT_SETTLEMENTS", "CreatePaymentSettlementCommand",
            {"canonical_public_id": settlement_id, "payment_intent_public_id": intent_id,
             "operational_account_public_id": _uuid(source, "operational_account_public_id"),
             "settlement_direction": "incoming", "gross_amount": amount, "fee_amount": fee,
             "net_amount": amount - fee, "currency_code": currency, "payment_method_code": method,
             "payment_rail_code": rail, "external_settlement_reference": external or None,
             "finality_status": "final", "evidence_hash": evidence_hash, "correlation_id": correlation},
            ("asset_increase", "unapplied_receipts_increase", "no_revenue"),
        )]
        if allocation:
            commands.append(cls._descriptor(
                envelope, 3, "XBOS_M50_RECEIVABLES_AND_CUSTOMER_BALANCES", "ReceiveReceivablePaymentCommand",
                {"payment_settlement_public_id": settlement_id,
                 "financial_obligation_public_id": _uuid(source, "financial_obligation_public_id"),
                 "amount": amount, "currency_code": currency, "correlation_id": correlation},
                ("receivable_decrease", "unapplied_receipts_decrease", "no_revenue"),
            ))
        return tuple(commands)

    @classmethod
    def _map_payment_settlement(cls, envelope: LegacyFinancialEnvelope, correlation: UUID):
        return cls._settlement_descriptors(envelope, correlation, allocation=False)

    @classmethod
    def _map_receivable_repayment(cls, envelope: LegacyFinancialEnvelope, correlation: UUID):
        return cls._settlement_descriptors(envelope, correlation, allocation=True)

    @classmethod
    def _map_refund(cls, envelope: LegacyFinancialEnvelope, correlation: UUID):
        source = envelope.payload
        amount = money(source.get("amount"), "amount", allow_zero=False)
        currency = _currency(source)
        evidence_hash = require_hash(source.get("evidence_hash"))
        return (cls._descriptor(
            envelope, 1, "XBOS_M54_REFUNDS_CORRECTIONS_AND_LOSS_EVENTS", "RecognizeRefundCommand",
            {"amount": amount, "currency_code": currency,
             "original_settlement_public_id": _uuid(source, "original_settlement_public_id"),
             "refund_settlement_public_id": _uuid(source, "refund_settlement_public_id"),
             "refund_reason": _text(source, "refund_reason").lower(),
             "document": {"document_type": "refund_notice", "document_number": _text(source, "document_number"),
                          "evidence_hash": evidence_hash},
             "correlation_id": correlation},
            ("settlement_out", "correction_append", "original_revenue_immutable"),
        ),)
