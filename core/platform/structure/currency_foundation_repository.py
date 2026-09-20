"""SQL-backed PC1 currency foundation; caller owns transaction scope."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .currency_foundation_contract import (
    CurrencyAsset,
    RegisterCurrencyAsset,
    SetTenantCurrencyPolicy,
    TenantCurrencyPolicy,
)
from .service import StructuralAuthorityError


class SQLCurrencyFoundationRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, values: dict[str, Any]) -> dict[str, Any] | None:
        row = self.session.execute(text(sql), values).mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _asset(row: dict[str, Any]) -> CurrencyAsset:
        return CurrencyAsset(
            code=row["code"],
            asset_kind=row["asset_kind"],
            display_name=row["display_name"],
            minor_unit_scale=row["minor_unit_scale"],
            maximum_storage_scale=row["maximum_storage_scale"],
            active=row["active"],
        )

    @staticmethod
    def _policy(row: dict[str, Any]) -> TenantCurrencyPolicy:
        return TenantCurrencyPolicy(
            tenant_id=row["tenant_id"],
            currency_code=row["currency_code"],
            rounding_mode=row["rounding_mode"],
            cash_rounding_increment=Decimal(row["cash_rounding_increment"]),
            active=row["active"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            policy_version=row["policy_version"],
        )

    def register_asset(
        self, command: RegisterCurrencyAsset, request_fingerprint: str
    ) -> CurrencyAsset:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": command.command_key},
        )
        existing = self._one(
            """SELECT code,asset_kind,display_name,minor_unit_scale,
                      maximum_storage_scale,active,metadata
               FROM public.currency_assets WHERE code=:code""",
            {"code": command.code},
        )
        expected = {
            "authority": command.authority_reference,
            "command_key": command.command_key,
            "request_fingerprint": request_fingerprint,
            "source_component": command.source_component,
            "source_record_id": command.source_record_id,
        }
        if existing:
            semantic = {
                "code": existing["code"],
                "asset_kind": existing["asset_kind"],
                "display_name": existing["display_name"],
                "minor_unit_scale": existing["minor_unit_scale"],
                "maximum_storage_scale": existing["maximum_storage_scale"],
                "active": existing["active"],
            }
            target = {
                "code": command.code,
                "asset_kind": command.asset_kind,
                "display_name": command.display_name,
                "minor_unit_scale": command.minor_unit_scale,
                "maximum_storage_scale": command.maximum_storage_scale,
                "active": command.active,
            }
            metadata = existing["metadata"] or {}
            if semantic == target and all(metadata.get(k) == v for k, v in expected.items()):
                return self._asset(existing)
            raise StructuralAuthorityError("currency_asset_conflict")

        row = self._one(
            """INSERT INTO public.currency_assets
               (code,asset_kind,display_name,minor_unit_scale,
                maximum_storage_scale,active,metadata)
               VALUES (:code,:kind,:name,:minor,:maximum,:active,CAST(:metadata AS jsonb))
               RETURNING code,asset_kind,display_name,minor_unit_scale,
                         maximum_storage_scale,active""",
            {
                "code": command.code,
                "kind": command.asset_kind,
                "name": command.display_name,
                "minor": command.minor_unit_scale,
                "maximum": command.maximum_storage_scale,
                "active": command.active,
                "metadata": json.dumps(expected, sort_keys=True),
            },
        )
        return self._asset(row)

    def set_tenant_policy(
        self, command: SetTenantCurrencyPolicy, request_fingerprint: str
    ) -> TenantCurrencyPolicy:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": command.command_key},
        )
        external_id = f"{command.currency_code}:{command.policy_version}"
        source = self._one(
            """SELECT metadata FROM public.kernel_source_records
               WHERE tenant_id=:tenant
                 AND source_component=:component
                 AND aggregate_type='tenant_currency_policy'
                 AND aggregate_external_id=:external""",
            {
                "tenant": command.tenant_id,
                "component": command.source_component,
                "external": external_id,
            },
        )
        policy = self._one(
            """SELECT tenant_id,currency_code,rounding_mode,cash_rounding_increment,
                      active,effective_from,effective_to,policy_version
               FROM public.tenant_currency_policies
               WHERE tenant_id=:tenant AND currency_code=:currency
                 AND policy_version=:version""",
            {
                "tenant": command.tenant_id,
                "currency": command.currency_code,
                "version": command.policy_version,
            },
        )
        evidence = {
            "authority": command.authority_reference,
            "command_key": command.command_key,
            "request_fingerprint": request_fingerprint,
        }
        if source or policy:
            if not source or not policy:
                raise StructuralAuthorityError("tenant_currency_policy_conflict")
            metadata = source["metadata"] or {}
            expected = TenantCurrencyPolicy(
                tenant_id=command.tenant_id,
                currency_code=command.currency_code,
                rounding_mode=command.rounding_mode,
                cash_rounding_increment=Decimal(command.cash_rounding_increment),
                active=command.active,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                policy_version=command.policy_version,
            )
            if self._policy(policy) == expected and all(
                metadata.get(k) == v for k, v in evidence.items()
            ):
                return self._policy(policy)
            raise StructuralAuthorityError("tenant_currency_policy_conflict")

        overlap = self._one(
            """SELECT id FROM public.tenant_currency_policies
               WHERE tenant_id=:tenant AND currency_code=:currency AND active
                 AND effective_from < COALESCE(:effective_to,'infinity'::timestamptz)
                 AND COALESCE(effective_to,'infinity'::timestamptz) > :effective_from
               LIMIT 1""",
            {
                "tenant": command.tenant_id,
                "currency": command.currency_code,
                "effective_from": command.effective_from,
                "effective_to": command.effective_to,
            },
        )
        if overlap:
            raise StructuralAuthorityError("tenant_currency_policy_overlap")

        row = self._one(
            """INSERT INTO public.tenant_currency_policies
               (tenant_id,currency_code,rounding_mode,cash_rounding_increment,
                active,effective_from,effective_to,policy_version)
               VALUES (:tenant,:currency,:mode,:increment,:active,
                       :effective_from,:effective_to,:version)
               RETURNING tenant_id,currency_code,rounding_mode,cash_rounding_increment,
                         active,effective_from,effective_to,policy_version""",
            {
                "tenant": command.tenant_id,
                "currency": command.currency_code,
                "mode": command.rounding_mode,
                "increment": command.cash_rounding_increment,
                "active": command.active,
                "effective_from": command.effective_from,
                "effective_to": command.effective_to,
                "version": command.policy_version,
            },
        )
        self.session.execute(
            text(
                """INSERT INTO public.kernel_source_records
                   (tenant_id,organization_unit_id,source_component,aggregate_type,
                    aggregate_external_id,aggregate_version,source_occurred_at,metadata)
                   VALUES (:tenant,NULL,:component,'tenant_currency_policy',
                           :external,:version,:occurred,CAST(:metadata AS jsonb))"""
            ),
            {
                "tenant": command.tenant_id,
                "component": command.source_component,
                "external": external_id,
                "version": str(command.policy_version),
                "occurred": command.effective_from,
                "metadata": json.dumps(evidence, sort_keys=True),
            },
        )
        return self._policy(row)
