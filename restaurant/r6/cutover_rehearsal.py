"""R6.2 deterministic WND production-cutover rehearsal helpers.

R6.2 does not switch production authority.  It classifies every rehearsed
financial source into mapped canonical shadow truth or an explicit withheld
exception and keeps the two sides reconcilable to the immutable WND snapshot.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

CONTROL_NAMES = (
    "commercial_revenue",
    "customer_allowances",
    "cash_collections",
    "receivables_opened",
    "receivables_satisfied",
    "refunds",
    "fulfillment_cost",
    "financial_documents",
)
WND_TIMEZONE = ZoneInfo("Africa/Douala")
WND_BUSINESS_DAY_START = time(8, 0)
_NAMESPACE = uuid5(NAMESPACE_URL, "xbos:r6.2:wnd-reference-release-cutover-rehearsal:v1")


def decimal(value: Any) -> Decimal:
    selected = Decimal(str(value or 0))
    if not selected.is_finite():
        raise ValueError("non-finite decimal")
    return selected


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def semantic_hash(value: Any) -> str:
    raw = json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def deterministic_public_id(kind: str, *parts: Any) -> UUID:
    selected = ":".join(str(p) for p in parts)
    return uuid5(_NAMESPACE, f"{kind}:{selected}")


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        # Track A legacy A/R timestamps are explicitly stored as UTC wall-clock naive.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def wnd_business_date(value: datetime) -> date:
    local = ensure_utc(value).astimezone(WND_TIMEZONE)
    selected = local.date()
    if local.timetz().replace(tzinfo=None) < WND_BUSINESS_DAY_START:
        selected -= timedelta(days=1)
    return selected


def zero_controls() -> dict[str, Decimal]:
    return {name: Decimal("0") for name in CONTROL_NAMES}


def add_controls(target: dict[str, Decimal], values: Mapping[str, Any]) -> None:
    for name in CONTROL_NAMES:
        target[name] = decimal(target.get(name, 0)) + decimal(values.get(name, 0))


def subtract_controls(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Decimal]:
    return {name: decimal(left.get(name, 0)) - decimal(right.get(name, 0)) for name in CONTROL_NAMES}


@dataclass
class WithheldLedger:
    counts: dict[str, int] = field(default_factory=dict)
    controls: dict[str, Decimal] = field(default_factory=zero_controls)
    _identities: list[str] = field(default_factory=list)

    def add(self, *, source_identity: str, reason: str, controls: Mapping[str, Any] | None = None) -> None:
        reason = str(reason).strip().lower()
        if not source_identity or not reason:
            raise ValueError("withheld identity and reason are required")
        self.counts[reason] = self.counts.get(reason, 0) + 1
        add_controls(self.controls, controls or {})
        self._identities.append(f"{source_identity}|{reason}")

    @property
    def fingerprint(self) -> str:
        return semantic_hash(sorted(self._identities))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "controls": dict(self.controls),
            "fingerprint": self.fingerprint,
        }


def assert_complete_reconciliation(
    source: Mapping[str, Any],
    mapped: Mapping[str, Any],
    withheld: Mapping[str, Any],
) -> None:
    for name in CONTROL_NAMES:
        expected = decimal(source.get(name, 0))
        actual = decimal(mapped.get(name, 0)) + decimal(withheld.get(name, 0))
        if actual != expected:
            raise ValueError(f"unreconciled control {name}: source={expected} mapped+withheld={actual}")
