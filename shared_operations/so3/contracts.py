"""Public SO3 inventory and stock-movement contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class MovementType(str, Enum):
    RECEIPT = "receipt"
    ISSUE = "issue"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUSTMENT_INCREASE = "adjustment_increase"
    ADJUSTMENT_DECREASE = "adjustment_decrease"
    COUNT_CORRECTION = "count_correction"
    RESERVATION_CONSUME = "reservation_consume"
    RESERVATION_RELEASE = "reservation_release"
    CORRECTION = "correction"


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class CountStatus(str, Enum):
    OPEN = "pending"
    ACCEPTED = "accepted"


@dataclass(frozen=True)
class StockLocation:
    id: int
    public_id: UUID
    tenant_id: int
    location_public_id: UUID
    code: str
    name: str
    active: bool
    legacy_branch_id: int | None


@dataclass(frozen=True)
class InventoryPosition:
    id: int
    public_id: UUID
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    on_hand: int
    reserved: int
    available: int
    reorder_level: int | None
    row_version: int


@dataclass(frozen=True)
class StockMovement:
    id: int
    public_id: UUID
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    movement_type: MovementType
    quantity_delta: int
    quantity_after: int
    reason_code: str
    source_type: str
    source_reference: str | None
    occurred_at: datetime
    correction_of_public_id: UUID | None = None
    related_public_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StockReservation:
    id: int
    public_id: UUID
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    quantity: int
    status: ReservationStatus
    source_type: str
    source_reference: str
    expires_at: datetime | None
    row_version: int


@dataclass(frozen=True)
class StockCount:
    id: int
    public_id: UUID
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    expected_quantity: int
    counted_quantity: int
    variance: int
    status: CountStatus
    reason_code: str
    occurred_at: datetime
    adjustment_movement_public_id: UUID | None
    row_version: int


@dataclass(frozen=True)
class RegisterStockLocation:
    command_key: str
    tenant_id: int
    location_public_id: UUID
    code: str
    name: str


@dataclass(frozen=True)
class MoveStock:
    command_key: str
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    quantity: int
    reason_code: str
    occurred_at: datetime
    source_type: str = "manual"
    source_reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransferStock:
    command_key: str
    tenant_id: int
    atomic_unit_public_id: UUID
    source_stock_location_public_id: UUID
    destination_stock_location_public_id: UUID
    quantity: int
    reason_code: str
    occurred_at: datetime
    source_type: str = "manual"
    source_reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReserveStock:
    command_key: str
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    quantity: int
    source_type: str
    source_reference: str
    occurred_at: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ChangeReservation:
    command_key: str
    tenant_id: int
    reservation_public_id: UUID
    expected_version: int
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class InitiateStockCount:
    command_key: str
    tenant_id: int
    atomic_unit_public_id: UUID
    stock_location_public_id: UUID
    counted_quantity: int
    reason_code: str
    occurred_at: datetime


@dataclass(frozen=True)
class AcceptStockCount:
    command_key: str
    tenant_id: int
    count_public_id: UUID
    expected_version: int
    occurred_at: datetime


@dataclass(frozen=True)
class CorrectMovement:
    command_key: str
    tenant_id: int
    movement_public_id: UUID
    reason_code: str
    occurred_at: datetime
