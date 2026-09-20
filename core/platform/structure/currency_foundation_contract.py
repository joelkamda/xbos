"""Additive PC1 currency-foundation contracts for XGI2."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RegisterCurrencyAsset:
    command_key: str
    code: str
    asset_kind: str
    display_name: str
    minor_unit_scale: int
    maximum_storage_scale: int
    active: bool = True
    authority_reference: str = "XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION"
    source_component: str = "pc1.currency_foundation"
    source_record_id: str = "currency-asset:XAF:v1"

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CurrencyAsset:
    code: str
    asset_kind: str
    display_name: str
    minor_unit_scale: int
    maximum_storage_scale: int
    active: bool


@dataclass(frozen=True)
class SetTenantCurrencyPolicy:
    command_key: str
    tenant_id: int
    currency_code: str
    rounding_mode: str
    cash_rounding_increment: Decimal
    active: bool
    effective_from: datetime
    policy_version: int
    effective_to: datetime | None = None
    authority_reference: str = "XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION"
    source_component: str = "pc1.currency_foundation"

    def canonical_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["cash_rounding_increment"] = format(self.cash_rounding_increment, "f")
        value["effective_from"] = self.effective_from.isoformat()
        value["effective_to"] = self.effective_to.isoformat() if self.effective_to else None
        return value


@dataclass(frozen=True)
class TenantCurrencyPolicy:
    tenant_id: int
    currency_code: str
    rounding_mode: str
    cash_rounding_increment: Decimal
    active: bool
    effective_from: datetime
    effective_to: datetime | None
    policy_version: int
