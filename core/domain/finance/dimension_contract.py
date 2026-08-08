"""Typed M2.5 posting-context contract for neutral financial dimensions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .event_contract import FinancialEventValidationError


DIMENSION_CONTRACT = "XBOS_M25_FINANCIAL_DIMENSIONS"
DIMENSION_CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise FinancialEventValidationError(
            "invalid_dimension_context", f"{name} must be a JSON object"
        )
    return value


def _dimension_code(value: Any) -> str:
    selected = str(value).strip().lower()
    if not _CODE.fullmatch(selected):
        raise FinancialEventValidationError(
            "invalid_dimension_code",
            "financial dimension codes must be lowercase snake-case identifiers",
        )
    return selected


def _value_code(value: Any) -> str:
    selected = str(value).strip()
    if not selected or len(selected) > 120:
        raise FinancialEventValidationError(
            "invalid_dimension_value_code",
            "financial dimension value codes must contain 1 to 120 characters",
        )
    return selected


@dataclass(frozen=True)
class PostingDimensionContext:
    global_values: Mapping[str, str]
    account_role_values: Mapping[str, Mapping[str, str]]

    def for_account_role(self, account_role: str) -> dict[str, str]:
        selected = dict(self.global_values)
        selected.update(self.account_role_values.get(account_role, {}))
        return selected

    def assert_roles_allowed(self, allowed_roles: set[str]) -> None:
        unknown = sorted(set(self.account_role_values) - allowed_roles)
        if unknown:
            raise FinancialEventValidationError(
                "dimension_account_role_not_posted",
                "dimension overrides target account roles absent from the posting: "
                + ", ".join(unknown),
            )


def parse_posting_dimension_context(
    posting_context: Mapping[str, Any],
) -> PostingDimensionContext:
    global_raw = _mapping(posting_context.get("dimension_values"), "dimension_values")
    role_raw = _mapping(
        posting_context.get("account_role_dimension_values"),
        "account_role_dimension_values",
    )

    global_values: dict[str, str] = {}
    for raw_dimension, raw_value in global_raw.items():
        dimension = _dimension_code(raw_dimension)
        if dimension in global_values:
            raise FinancialEventValidationError(
                "duplicate_dimension_code", f"duplicate dimension code {dimension}"
            )
        global_values[dimension] = _value_code(raw_value)

    role_values: dict[str, Mapping[str, str]] = {}
    for raw_role, raw_values in role_raw.items():
        role = str(raw_role).strip().lower()
        if not _CODE.fullmatch(role):
            raise FinancialEventValidationError(
                "invalid_dimension_account_role",
                "dimension override account roles must be lowercase identifiers",
            )
        values = _mapping(raw_values, f"account_role_dimension_values.{role}")
        cleaned: dict[str, str] = {}
        for raw_dimension, raw_value in values.items():
            dimension = _dimension_code(raw_dimension)
            if dimension in cleaned:
                raise FinancialEventValidationError(
                    "duplicate_dimension_code", f"duplicate dimension code {dimension}"
                )
            cleaned[dimension] = _value_code(raw_value)
        role_values[role] = cleaned

    return PostingDimensionContext(global_values, role_values)
