"""Nonoperative WND V3 parity contracts. No DB, HTTP, printer, stock or money writer.

DraftRepository is a PORT, not installed storage. The memory implementation is
a local test double only; real save/reload needs separate tenant-scoped durable
persistence, authorization, versioning, migrations and rollback admission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from json import dumps
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from restaurant.wnd_operational_policy import WND_POLICY

DOUALA = ZoneInfo("Africa/Douala")
VALID_SHIFTS = frozenset({"day", "night", "full24"})


class WParityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Window:
    business_date: date
    shift: str
    start_utc: datetime
    end_utc: datetime


def business_window_at(instant: datetime) -> Window:
    if not isinstance(instant, datetime) or not instant.tzinfo or instant.utcoffset() is None:
        raise WParityError("W_AWARE_TIME_REQUIRED")
    local = instant.astimezone(DOUALA)
    business_day = local.date() - timedelta(days=1) if local.time() < time(8, 0) else local.date()
    shift = "day" if time(8, 0) <= local.time() < time(18, 0) else "night"
    return window_for(business_day, shift)


def window_for(business_day: date, shift: str) -> Window:
    if not isinstance(business_day, date) or isinstance(business_day, datetime):
        raise WParityError("W_BUSINESS_DATE_INVALID")
    if shift not in VALID_SHIFTS:
        raise WParityError("W_SHIFT_INVALID")
    start_hour = 18 if shift == "night" else 8
    duration = timedelta(hours=14 if shift == "night" else 10 if shift == "day" else 24)
    start = datetime.combine(business_day, time(start_hour, 0), tzinfo=DOUALA)
    return Window(business_day, shift, start.astimezone(timezone.utc),
                  (start + duration).astimezone(timezone.utc))


@dataclass(frozen=True)
class DraftScope:
    tenant_id: int
    branch_id: int
    business_date: date
    shift: str


@dataclass(frozen=True)
class CountedLine:
    atomic_unit_id: int
    counted_qty: int
    note: str = ""


@dataclass(frozen=True)
class StockDraft:
    scope: DraftScope
    revision: int
    lines: tuple[CountedLine, ...]
    note: str
    fingerprint: str


class DraftRepository(Protocol):
    def load(self, scope: DraftScope) -> StockDraft | None: ...
    def put_if_revision(self, item: StockDraft, expected_revision: int) -> bool: ...


class MemoryDraftFixtureRepository:
    """NOT DURABLE, never use for production WND; synthetic test double only."""
    def __init__(self):
        self.snapshots: dict[DraftScope, StockDraft] = {}

    def load(self, scope: DraftScope) -> StockDraft | None:
        return self.snapshots.get(scope)

    def put_if_revision(self, item: StockDraft, expected_revision: int) -> bool:
        current = self.load(item.scope)
        if (current.revision if current else 0) != expected_revision:
            return False
        self.snapshots[item.scope] = item
        return True


class StockDraftAuthority:
    def __init__(self, store: DraftRepository, *,
                 authorize: Callable[[int, int, str], bool],
                 closed_window: Callable[[DraftScope], bool]):
        self._store, self._authorize, self._closed = store, authorize, closed_window

    def _scope(self, scope: DraftScope, permission: str) -> None:
        if (not isinstance(scope, DraftScope)
                or type(scope.tenant_id) is not int or scope.tenant_id < 1
                or type(scope.branch_id) is not int or scope.branch_id < 1):
            raise WParityError("W_STOCK_SCOPE_INVALID")
        window_for(scope.business_date, scope.shift)
        if not self._authorize(scope.tenant_id, scope.branch_id, permission):
            raise WParityError("W_STOCK_PERMISSION_DENIED")

    def reload(self, scope: DraftScope) -> StockDraft | None:
        self._scope(scope, "inventory.reconcile.read")
        return self._store.load(scope)

    def save(self, scope: DraftScope, *, expected_revision: int,
             lines: tuple[CountedLine, ...], note: str = "") -> StockDraft:
        self._scope(scope, "inventory.reconcile.save")
        if self._closed(scope):
            raise WParityError("W_STOCK_WINDOW_ALREADY_CLOSED")
        if type(expected_revision) is not int or expected_revision < 0:
            raise WParityError("W_STOCK_REVISION_INVALID")
        if not isinstance(lines, tuple) or not lines:
            raise WParityError("W_STOCK_LINES_REQUIRED")
        seen: set[int] = set()
        cleaned: list[CountedLine] = []
        for line in lines:
            if not isinstance(line, CountedLine):
                raise WParityError("W_STOCK_LINE_INVALID")
            if (type(line.atomic_unit_id) is not int or line.atomic_unit_id <= 0
                    or type(line.counted_qty) is not int or line.counted_qty < 0):
                raise WParityError("W_STOCK_LINE_INVALID")
            if line.atomic_unit_id in seen:
                raise WParityError("W_STOCK_DUPLICATE_UNIT")
            seen.add(line.atomic_unit_id)
            cleaned.append(CountedLine(line.atomic_unit_id, line.counted_qty, line.note.strip()))
        cleaned.sort(key=lambda x: x.atomic_unit_id)
        note = str(note).strip()
        identity = {
            "tenant_id": scope.tenant_id, "branch_id": scope.branch_id,
            "business_date": scope.business_date.isoformat(), "shift": scope.shift,
            "lines": [x.__dict__ for x in cleaned], "note": note,
        }
        fp = sha256(dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        current = self._store.load(scope)
        # Exact retry never mutates a draft, even if caller holds an old revision.
        if current is not None and current.fingerprint == fp:
            return current
        version = current.revision if current else 0
        if version != expected_revision:
            raise WParityError("W_STOCK_STALE_DRAFT")
        saved = StockDraft(scope, version + 1, tuple(cleaned), note, fp)
        if not self._store.put_if_revision(saved, expected_revision):
            raise WParityError("W_STOCK_CONCURRENT_SAVE")
        return saved

    def variance_preview(self, scope: DraftScope, *,
                         system_quantities: dict[int, int],
                         expected_revision: int) -> dict:
        """Read-only calculation. NOT the real R6 close or stock movement."""
        self._scope(scope, "inventory.reconcile.read")
        current = self._store.load(scope)
        if current is None or current.revision != expected_revision:
            raise WParityError("W_STOCK_DRAFT_MISSING_OR_STALE")
        if self._closed(scope):
            raise WParityError("W_STOCK_WINDOW_ALREADY_CLOSED")
        if set(system_quantities) != {x.atomic_unit_id for x in current.lines}:
            raise WParityError("W_STOCK_SYSTEM_BASIS_INCOMPLETE")
        rows = []
        for line in current.lines:
            system = system_quantities[line.atomic_unit_id]
            if type(system) is not int or system < 0:
                raise WParityError("W_STOCK_SYSTEM_BASIS_INVALID")
            rows.append({"atomic_unit_id": line.atomic_unit_id,
                         "system_qty": system, "counted_qty": line.counted_qty,
                         "variance_qty": line.counted_qty - system})
        return {"draft_revision": current.revision, "fingerprint": current.fingerprint,
                "lines": rows, "has_variance": any(x["variance_qty"] for x in rows),
                "stock_effects": 0, "finance_effects": 0,
                "real_close_allowed": False}


@dataclass(frozen=True)
class Tender:
    method: str
    whole_xaf: int


def tender_and_receivable_preview(*, charge_whole_xaf: int,
                                  tenders: tuple[Tender, ...],
                                  unpaid_allowed: bool) -> dict:
    if type(charge_whole_xaf) is not int or charge_whole_xaf <= 0:
        raise WParityError("W_PAYMENT_CHARGE_INVALID")
    if not isinstance(tenders, tuple) or len(tenders) > 16:
        raise WParityError("W_PAYMENT_TENDER_COUNT")
    total = 0
    for tender in tenders:
        if (not isinstance(tender, Tender) or tender.method not in
                {"cash", "mtn", "orange", "bank", "xafpay"}
                or type(tender.whole_xaf) is not int or tender.whole_xaf <= 0):
            raise WParityError("W_PAYMENT_TENDER_INVALID")
        total += tender.whole_xaf
    if total > charge_whole_xaf:
        raise WParityError("W_PAYMENT_SPLIT_OVERCAPACITY")
    if total < charge_whole_xaf and not unpaid_allowed:
        raise WParityError("W_PAYMENT_UNPAID_NOT_ALLOWED")
    return {"charge_whole_xaf": charge_whole_xaf, "tender_intended_whole_xaf": total,
            "receivable_proposed_whole_xaf": charge_whole_xaf - total,
            "provider_verified": False, "finance_posted": False,
            "paid_assertion_allowed": False}


def kitchen_intent_preview(*, server_category: str,
                           server_subcategory: str, status: str = "waiting") -> dict:
    """Uses existing WND food-only routing policy; no kitchen ticket is fired."""
    category = server_category.strip().upper()
    subcategory = server_subcategory.strip().upper()
    result = WND_POLICY.fulfillment({category, subcategory}, category, subcategory, status)
    return {**result, "kitchen_effects": 0, "source": "WND_POLICY_SYNTHETIC"}


def receipt_80mm_preview(*, legal_name: str, niu: str,
                         charge_whole_xaf: int, remainder_whole_xaf: int) -> dict:
    if not legal_name.strip() or not niu.strip():
        raise WParityError("W_RECEIPT_LEGAL_ID_REQUIRED")
    if (type(charge_whole_xaf) is not int or charge_whole_xaf < 0 or
            type(remainder_whole_xaf) is not int or
            remainder_whole_xaf < 0 or remainder_whole_xaf > charge_whole_xaf):
        raise WParityError("W_RECEIPT_AMOUNT_INVALID")
    return {"paper_mm": 80, "business": legal_name.strip(), "niu": niu.strip(),
            "due_whole_xaf": remainder_whole_xaf, "charge_whole_xaf": charge_whole_xaf,
            "document_status": "PROFORMA_UNVERIFIED_PAYMENT",
            "real_printer_effects": 0, "legal_tax_validation": "OWNER_PENDING"}


def manager_close_preview(*, m6_asof_verified: bool, open_stock_drafts: int,
                          unexplained_variances: int, uncertain_provider_attempts: int) -> dict:
    values = (open_stock_drafts, unexplained_variances, uncertain_provider_attempts)
    if any(type(x) is not int or x < 0 for x in values):
        raise WParityError("W_CLOSE_INPUT_INVALID")
    ready = bool(m6_asof_verified and not any(values))
    return {"disposition": "LOCAL_CANDIDATE_ONLY" if ready else "HOLD",
            "actual_m6_close": False, "finance_effects": 0, "source": "W_D1D2_SOURCE_CANDIDATE"}
