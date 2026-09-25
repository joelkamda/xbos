from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .contracts import H1BError

_FIELDS = ("country_code", "region", "city", "district", "postal_prefix")


def normalize_address_value(value: Any) -> str | None:
    if value is None:
        return None
    selected = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return selected or None


def normalized_address(contact_value: str, metadata: dict[str, Any] | None) -> dict[str, str | None]:
    source: dict[str, Any] = {}
    meta = metadata or {}
    if isinstance(meta.get("address"), dict):
        source.update(meta["address"])
    for field in _FIELDS:
        if field in meta:
            source[field] = meta[field]
    if not source:
        try:
            parsed = json.loads(contact_value)
            if isinstance(parsed, dict):
                source.update(parsed)
        except Exception:
            pass
    result = {field: normalize_address_value(source.get(field)) for field in _FIELDS}
    if not any(result.values()):
        raise H1BError("CONTEXT_MISMATCH")
    return result


@dataclass(frozen=True, slots=True)
class DeliveryPolicyRecord:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    location_id: int
    policy_code: str
    policy_version: int
    address_match_rule: dict[str, Any]
    fee_catalog_entry_public_id: UUID
    fee_price_public_id: UUID
    effective_from: datetime
    effective_to: datetime | None
    active: bool


def _matches(rule: dict[str, Any], address: dict[str, str | None]) -> bool:
    for field in _FIELDS:
        expected = normalize_address_value(rule.get(field))
        if expected is None:
            continue
        actual = address.get(field)
        if actual is None:
            return False
        if field == "postal_prefix":
            if not actual.startswith(expected):
                return False
        elif actual != expected:
            return False
    return True


def _specificity(rule: dict[str, Any]) -> int:
    return sum(1 for field in _FIELDS if normalize_address_value(rule.get(field)) is not None)


def select_delivery_policy(
    policies: tuple[DeliveryPolicyRecord, ...],
    *,
    address: dict[str, str | None],
    at: datetime,
) -> DeliveryPolicyRecord:
    eligible = tuple(
        p for p in policies
        if p.active
        and p.effective_from <= at
        and (p.effective_to is None or at < p.effective_to)
        and _matches(p.address_match_rule, address)
    )
    if not eligible:
        raise H1BError("ORDER_NOT_READY")
    ranked = sorted(eligible, key=lambda p: (_specificity(p.address_match_rule), p.policy_version), reverse=True)
    best_specificity = _specificity(ranked[0].address_match_rule)
    best = tuple(p for p in ranked if _specificity(p.address_match_rule) == best_specificity)
    if len(best) != 1:
        raise H1BError("ORDER_NOT_READY")
    return best[0]
