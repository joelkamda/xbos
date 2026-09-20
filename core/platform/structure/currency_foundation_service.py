"""PC1 additive currency master-data and tenant-policy authority."""
from __future__ import annotations

import hashlib
import json
from datetime import timezone
from decimal import Decimal
from typing import Protocol

from .currency_foundation_contract import (
    CurrencyAsset,
    RegisterCurrencyAsset,
    SetTenantCurrencyPolicy,
    TenantCurrencyPolicy,
)
from .service import StructuralAuthorityError


class CurrencyFoundationRepository(Protocol):
    def register_asset(
        self, command: RegisterCurrencyAsset, request_fingerprint: str
    ) -> CurrencyAsset: ...
    def set_tenant_policy(
        self, command: SetTenantCurrencyPolicy, request_fingerprint: str
    ) -> TenantCurrencyPolicy: ...


class CurrencyFoundationAuthority:
    def __init__(self, repository: CurrencyFoundationRepository):
        self.repository = repository

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def register_asset(self, command: RegisterCurrencyAsset) -> CurrencyAsset:
        if (
            not command.command_key.strip()
            or command.code != command.code.strip().upper()
            or not command.code
            or command.asset_kind not in {"fiat", "crypto", "points", "other"}
            or not command.display_name.strip()
            or not 0 <= command.minor_unit_scale <= 8
            or not command.minor_unit_scale <= command.maximum_storage_scale <= 8
        ):
            raise StructuralAuthorityError("invalid_currency_asset")
        return self.repository.register_asset(
            command, self._fingerprint(command.canonical_payload())
        )

    def set_tenant_policy(
        self, command: SetTenantCurrencyPolicy
    ) -> TenantCurrencyPolicy:
        if command.effective_from.tzinfo is None:
            raise StructuralAuthorityError("currency_policy_timestamp_not_aware")
        if command.effective_to is not None and command.effective_to.tzinfo is None:
            raise StructuralAuthorityError("currency_policy_timestamp_not_aware")
        if (
            not command.command_key.strip()
            or command.tenant_id <= 0
            or command.currency_code != command.currency_code.strip().upper()
            or not command.currency_code
            or not command.rounding_mode.strip()
            or Decimal(command.cash_rounding_increment) < 0
            or command.policy_version <= 0
            or (
                command.effective_to is not None
                and command.effective_to.astimezone(timezone.utc)
                <= command.effective_from.astimezone(timezone.utc)
            )
        ):
            raise StructuralAuthorityError("invalid_tenant_currency_policy")
        return self.repository.set_tenant_policy(
            command, self._fingerprint(command.canonical_payload())
        )
