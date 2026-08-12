"""Schema-neutral M8.1 contracts for delayed/offline financial facts and authority probes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable


class AdversarialControlError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _text(value: object, field: str, limit: int = 200) -> str:
    selected = str(value).strip()
    if not selected or len(selected) > limit:
        raise AdversarialControlError(f"invalid_{field}", field)
    return selected


def _instant(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AdversarialControlError("timezone_required", field)
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DelayedFinancialFact:
    tenant_id: int
    organization_unit_id: int
    source_system: str
    source_record_id: str
    source_sequence: int
    occurred_at: datetime
    received_at: datetime
    business_date: date
    fact_kind: str
    payload_fingerprint: str
    correction_of: str | None = None

    def __post_init__(self) -> None:
        if self.tenant_id <= 0 or self.organization_unit_id <= 0:
            raise AdversarialControlError("positive_scope_required", "tenant/org")
        object.__setattr__(self, "source_system", _text(self.source_system, "source_system", 80))
        object.__setattr__(self, "source_record_id", _text(self.source_record_id, "source_record_id"))
        object.__setattr__(self, "fact_kind", _text(self.fact_kind, "fact_kind", 80).lower())
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "received_at", _instant(self.received_at, "received_at"))
        if not isinstance(self.business_date, date) or isinstance(self.business_date, datetime):
            raise AdversarialControlError("invalid_business_date", "business_date")
        if self.source_sequence < 0:
            raise AdversarialControlError("invalid_source_sequence", "source_sequence")
        fingerprint = str(self.payload_fingerprint).strip().lower()
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise AdversarialControlError("invalid_payload_fingerprint", "payload_fingerprint")
        object.__setattr__(self, "payload_fingerprint", fingerprint)
        if self.correction_of is not None:
            object.__setattr__(self, "correction_of", _text(self.correction_of, "correction_of"))

    @property
    def identity(self) -> tuple[int, str, str]:
        return self.tenant_id, self.source_system, self.source_record_id

    @property
    def ordering_key(self) -> tuple[object, ...]:
        return (
            self.business_date, self.occurred_at, self.source_sequence,
            self.source_system, self.source_record_id, self.payload_fingerprint,
        )

    @property
    def semantic_fingerprint(self) -> str:
        payload = {
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "source_sequence": self.source_sequence,
            "occurred_at": _time_text(self.occurred_at),
            "business_date": self.business_date.isoformat(),
            "fact_kind": self.fact_kind,
            "payload_fingerprint": self.payload_fingerprint,
            "correction_of": self.correction_of,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AuthorityProbe:
    tenant_id: int
    organization_unit_id: int
    action: str
    actor_user_id: int
    actor_permissions: frozenset[str]
    approved_by_user_id: int | None = None
    approver_permissions: frozenset[str] = frozenset()
    evidence_fingerprint: str | None = None


REQUIRED_PERMISSION = {
    "post_financial_fact": "accounting.post",
    "reconcile": "accounting.reconcile",
    "close_period": "accounting.close_period",
    "reopen_period": "accounting.close_period",
    "refund": "payments.refund",
}


def fact_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require_single_scope(facts: Iterable[DelayedFinancialFact]) -> tuple[int, int]:
    scopes = {(fact.tenant_id, fact.organization_unit_id) for fact in facts}
    if len(scopes) != 1:
        raise AdversarialControlError("scope_mismatch", repr(sorted(scopes)))
    return next(iter(scopes))
