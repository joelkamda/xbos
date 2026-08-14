"""Neutral SO3 inventory authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Callable, Protocol
from uuid import UUID, uuid4

from .contracts import (
    AcceptStockCount,
    ChangeReservation,
    CorrectMovement,
    CountStatus,
    InitiateStockCount,
    InventoryPosition,
    MoveStock,
    MovementType,
    RegisterStockLocation,
    ReservationStatus,
    ReserveStock,
    StockCount,
    StockLocation,
    StockMovement,
    StockReservation,
    TransferStock,
)


class SO3AuthorityError(RuntimeError):
    def __init__(self, code: str, category: str, safe_explanation: str, *, retryable: bool = False, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.category = category
        self.safe_explanation = safe_explanation
        self.retryable = retryable
        self.details = details or {}


class SO3Repository(Protocol):
    def register_location(self, command, location_id: int, public_id: UUID, fingerprint: str) -> StockLocation: ...
    def position(self, tenant_id: int, atomic_unit_id: int, stock_location_id: int) -> InventoryPosition | None: ...
    def list_positions(self, tenant_id: int, stock_location_id: int | None = None) -> tuple[InventoryPosition, ...]: ...
    def apply_movement(self, command, atomic_unit_id: int, stock_location_id: int, movement_type: MovementType, quantity_delta: int, fingerprint: str, allow_negative: bool, public_id: UUID, correction_of_id: int | None = None, related_public_id: UUID | None = None) -> tuple[InventoryPosition, StockMovement]: ...
    def transfer(self, command, atomic_unit_id: int, source_location_id: int, destination_location_id: int, fingerprint: str, allow_negative: bool, transfer_public_id: UUID, outbound_public_id: UUID, inbound_public_id: UUID) -> tuple[StockMovement, StockMovement]: ...
    def reserve(self, command, atomic_unit_id: int, stock_location_id: int, fingerprint: str, public_id: UUID) -> StockReservation: ...
    def reservation(self, tenant_id: int, public_id: UUID) -> StockReservation | None: ...
    def change_reservation(self, command, fingerprint: str, target: ReservationStatus, movement_public_id: UUID | None = None) -> StockReservation | None: ...
    def initiate_count(self, command, atomic_unit_id: int, stock_location_id: int, fingerprint: str, public_id: UUID) -> StockCount: ...
    def count(self, tenant_id: int, public_id: UUID) -> StockCount | None: ...
    def accept_count(self, command, fingerprint: str, movement_public_id: UUID) -> StockCount | None: ...
    def movement(self, tenant_id: int, public_id: UUID) -> StockMovement | None: ...
    def correct(self, command, fingerprint: str, public_id: UUID) -> StockMovement: ...
    def movements(self, tenant_id: int, atomic_unit_id: int | None = None, stock_location_id: int | None = None) -> tuple[StockMovement, ...]: ...


class SO3Authority:
    def __init__(
        self,
        repository: SO3Repository,
        *,
        atomic_unit_resolver: Callable[[int, UUID], object | None],
        location_resolver: Callable[[int, UUID], object | None],
        authorize: Callable[[int, str, str, int | None], bool],
        negative_stock_policy: Callable[[int, UUID, UUID], bool] = lambda *_: False,
        public_id_factory: Callable[[], UUID] = uuid4,
    ):
        self.repository = repository
        self.atomic_unit_resolver = atomic_unit_resolver
        self.location_resolver = location_resolver
        self.authorize = authorize
        self.negative_stock_policy = negative_stock_policy
        self.public_id_factory = public_id_factory

    @staticmethod
    def _fingerprint(command: object) -> str:
        return hashlib.sha256(json.dumps(asdict(command), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    @staticmethod
    def _code(value: str, field: str) -> str:
        code = value.strip().lower()
        if not code or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in code):
            raise SO3AuthorityError(f"SO3_INVALID_{field.upper()}", "validation_failure", f"{field} must be a stable neutral code")
        return code

    @staticmethod
    def _positive(value: int, field: str = "quantity") -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SO3AuthorityError(f"SO3_INVALID_{field.upper()}", "validation_failure", f"{field} must be a positive integer")
        return value

    @staticmethod
    def _json_object(value: dict) -> dict:
        if not isinstance(value, dict):
            raise SO3AuthorityError("SO3_INVALID_METADATA", "validation_failure", "metadata must be an object")
        try:
            json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise SO3AuthorityError("SO3_INVALID_METADATA", "validation_failure", "metadata must be JSON-safe") from exc
        return value

    def _permit(self, tenant_id: int, permission: str, scope: str = "tenant", scope_id: int | None = None) -> None:
        if not self.authorize(tenant_id, permission, scope, scope_id):
            raise SO3AuthorityError("SO3_PERMISSION_DENIED", "permission_denied", "The requested inventory operation is not permitted")

    def _atomic(self, tenant_id: int, public_id: UUID) -> object:
        unit = self.atomic_unit_resolver(tenant_id, public_id)
        if unit is None or getattr(unit, "tenant_id", None) != tenant_id or UUID(str(getattr(unit, "public_id", UUID(int=0)))) != public_id:
            raise SO3AuthorityError("SO3_ATOMIC_UNIT_NOT_FOUND", "scope_mismatch", "The SO1 Atomic Unit was not found in this tenant")
        return unit

    def _location(self, tenant_id: int, public_id: UUID) -> object:
        location = self.location_resolver(tenant_id, public_id)
        if location is None or getattr(location, "tenant_id", None) != tenant_id or UUID(str(getattr(location, "public_id", UUID(int=0)))) != public_id:
            raise SO3AuthorityError("SO3_LOCATION_NOT_FOUND", "scope_mismatch", "The PC1 location was not found in this tenant")
        return location

    def register_stock_location(self, command: RegisterStockLocation) -> StockLocation:
        self._permit(command.tenant_id, "inventory.location.manage")
        location = self._location(command.tenant_id, command.location_public_id)
        normalized = replace(command, code=self._code(command.code, "location_code"), name=command.name.strip())
        if not normalized.name:
            raise SO3AuthorityError("SO3_INVALID_LOCATION_NAME", "validation_failure", "Stock-location name is required")
        return self.repository.register_location(normalized, int(location.id), self.public_id_factory(), self._fingerprint(normalized))

    def position(self, tenant_id: int, atomic_unit_public_id: UUID, stock_location_public_id: UUID) -> InventoryPosition:
        self._permit(tenant_id, "inventory.read")
        unit = self._atomic(tenant_id, atomic_unit_public_id)
        location = self._location(tenant_id, stock_location_public_id)
        result = self.repository.position(tenant_id, int(unit.id), int(location.id))
        if result is None:
            raise SO3AuthorityError("SO3_POSITION_NOT_FOUND", "not_found", "The inventory position was not found")
        return result

    def list_positions(self, tenant_id: int, stock_location_public_id: UUID | None = None) -> tuple[InventoryPosition, ...]:
        self._permit(tenant_id, "inventory.read")
        location_id = int(self._location(tenant_id, stock_location_public_id).id) if stock_location_public_id else None
        return self.repository.list_positions(tenant_id, location_id)

    def _move(self, command: MoveStock, movement_type: MovementType, sign: int) -> tuple[InventoryPosition, StockMovement]:
        permission = "inventory.receive" if movement_type is MovementType.RECEIPT else "inventory.issue" if movement_type is MovementType.ISSUE else "inventory.adjust"
        self._permit(command.tenant_id, permission)
        unit = self._atomic(command.tenant_id, command.atomic_unit_public_id)
        location = self._location(command.tenant_id, command.stock_location_public_id)
        normalized = replace(command, quantity=self._positive(command.quantity), reason_code=self._code(command.reason_code, "reason"), source_type=self._code(command.source_type, "source"), metadata=self._json_object(command.metadata))
        allow_negative = self.negative_stock_policy(command.tenant_id, command.atomic_unit_public_id, command.stock_location_public_id)
        return self.repository.apply_movement(normalized, int(unit.id), int(location.id), movement_type, sign * normalized.quantity, self._fingerprint(normalized), allow_negative, self.public_id_factory())

    def receive(self, command: MoveStock) -> tuple[InventoryPosition, StockMovement]:
        return self._move(command, MovementType.RECEIPT, 1)

    def issue(self, command: MoveStock) -> tuple[InventoryPosition, StockMovement]:
        return self._move(command, MovementType.ISSUE, -1)

    def adjust(self, command: MoveStock, *, increase: bool) -> tuple[InventoryPosition, StockMovement]:
        return self._move(command, MovementType.ADJUSTMENT_INCREASE if increase else MovementType.ADJUSTMENT_DECREASE, 1 if increase else -1)

    def transfer(self, command: TransferStock) -> tuple[StockMovement, StockMovement]:
        self._permit(command.tenant_id, "inventory.transfer")
        if command.source_stock_location_public_id == command.destination_stock_location_public_id:
            raise SO3AuthorityError("SO3_TRANSFER_SAME_LOCATION", "validation_failure", "Transfer locations must differ")
        unit = self._atomic(command.tenant_id, command.atomic_unit_public_id)
        source = self._location(command.tenant_id, command.source_stock_location_public_id)
        destination = self._location(command.tenant_id, command.destination_stock_location_public_id)
        normalized = replace(command, quantity=self._positive(command.quantity), reason_code=self._code(command.reason_code, "reason"), source_type=self._code(command.source_type, "source"), metadata=self._json_object(command.metadata))
        allow_negative = self.negative_stock_policy(command.tenant_id, command.atomic_unit_public_id, command.source_stock_location_public_id)
        return self.repository.transfer(normalized, int(unit.id), int(source.id), int(destination.id), self._fingerprint(normalized), allow_negative, self.public_id_factory(), self.public_id_factory(), self.public_id_factory())

    def reserve(self, command: ReserveStock) -> StockReservation:
        self._permit(command.tenant_id, "inventory.reserve")
        unit = self._atomic(command.tenant_id, command.atomic_unit_public_id)
        location = self._location(command.tenant_id, command.stock_location_public_id)
        normalized = replace(command, quantity=self._positive(command.quantity), source_type=self._code(command.source_type, "source"), source_reference=command.source_reference.strip())
        if not normalized.source_reference or (normalized.expires_at and normalized.expires_at <= normalized.occurred_at):
            raise SO3AuthorityError("SO3_INVALID_RESERVATION", "validation_failure", "Reservation source and expiry must be valid")
        return self.repository.reserve(normalized, int(unit.id), int(location.id), self._fingerprint(normalized), self.public_id_factory())

    def _change_reservation(self, command: ChangeReservation, target: ReservationStatus) -> StockReservation:
        self._permit(command.tenant_id, "inventory.reserve")
        normalized = replace(command, reason_code=self._code(command.reason_code, "reason"))
        result = self.repository.change_reservation(normalized, self._fingerprint(normalized), target, self.public_id_factory() if target in {ReservationStatus.RELEASED, ReservationStatus.CONSUMED} else None)
        if result is None:
            raise SO3AuthorityError("SO3_RESERVATION_STALE", "stale_version", "The reservation changed; reload before retrying", retryable=True)
        return result

    def release_reservation(self, command: ChangeReservation) -> StockReservation:
        return self._change_reservation(command, ReservationStatus.RELEASED)

    def consume_reservation(self, command: ChangeReservation) -> StockReservation:
        return self._change_reservation(command, ReservationStatus.CONSUMED)

    def initiate_count(self, command: InitiateStockCount) -> StockCount:
        self._permit(command.tenant_id, "inventory.count")
        unit = self._atomic(command.tenant_id, command.atomic_unit_public_id)
        location = self._location(command.tenant_id, command.stock_location_public_id)
        if isinstance(command.counted_quantity, bool) or not isinstance(command.counted_quantity, int) or command.counted_quantity < 0:
            raise SO3AuthorityError("SO3_INVALID_COUNT", "validation_failure", "Counted quantity must be a non-negative integer")
        normalized = replace(command, reason_code=self._code(command.reason_code, "reason"))
        return self.repository.initiate_count(normalized, int(unit.id), int(location.id), self._fingerprint(normalized), self.public_id_factory())

    def accept_count(self, command: AcceptStockCount) -> StockCount:
        self._permit(command.tenant_id, "inventory.count.accept")
        result = self.repository.accept_count(command, self._fingerprint(command), self.public_id_factory())
        if result is None:
            raise SO3AuthorityError("SO3_COUNT_STALE", "stale_version", "The stock count changed; reload before retrying", retryable=True)
        return result

    def correct_movement(self, command: CorrectMovement) -> StockMovement:
        self._permit(command.tenant_id, "inventory.adjust")
        original = self.repository.movement(command.tenant_id, command.movement_public_id)
        if original is None:
            raise SO3AuthorityError("SO3_MOVEMENT_NOT_FOUND", "not_found", "The movement was not found")
        if original.movement_type is MovementType.CORRECTION:
            raise SO3AuthorityError("SO3_CORRECTION_CHAIN_FORBIDDEN", "validation_failure", "Correct the original movement, not a correction")
        normalized = replace(command, reason_code=self._code(command.reason_code, "reason"))
        return self.repository.correct(normalized, self._fingerprint(normalized), self.public_id_factory())

    def movement_history(self, tenant_id: int, atomic_unit_public_id: UUID | None = None, stock_location_public_id: UUID | None = None) -> tuple[StockMovement, ...]:
        self._permit(tenant_id, "inventory.read")
        atomic_id = int(self._atomic(tenant_id, atomic_unit_public_id).id) if atomic_unit_public_id else None
        location_id = int(self._location(tenant_id, stock_location_public_id).id) if stock_location_public_id else None
        return self.repository.movements(tenant_id, atomic_id, location_id)
