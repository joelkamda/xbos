from typing import Any, Dict, Optional

from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.inventory.service import InventoryService
from core.domain.inventory.repository import InventoryRepository
from core.errors.api_error import APIError


class InventoryController:
    """
    HTTP controller for Inventory.

    Responsibilities:
    - Extract tenant / branch context
    - Delegate to InventoryService / Repository
    - Return audit-friendly payloads
    - NO business logic

    Inventory model:
    - InventoryMovement is source of truth.
    - InventoryItem.quantity_on_hand is cached state.
    """

    def __init__(self):
        pass

    # -------------------------------------------------
    # Context
    # -------------------------------------------------

    def _ctx(self, request: Request) -> Dict[str, Any]:
        ctx = getattr(request.state, "user", None)

        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        if not ctx.get("tenant_id") or not ctx.get("branch_id"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant or branch context",
            )

        return ctx

    def _int_payload(
        self,
        payload: dict,
        key: str,
        *,
        required: bool = True,
        default: Optional[int] = None,
    ) -> Optional[int]:
        value = payload.get(key)

        if value is None or value == "":
            if required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{key} is required",
                )
            return default

        try:
            return int(value)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be an integer",
            )

    def _float_payload(
        self,
        payload: dict,
        key: str,
        *,
        required: bool = False,
        default: Optional[float] = None,
    ) -> Optional[float]:
        value = payload.get(key)

        if value is None or value == "":
            if required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{key} is required",
                )
            return default

        try:
            return float(value)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a number",
            )

    def _bool_payload(
        self,
        payload: dict,
        key: str,
        *,
        default: bool = False,
    ) -> bool:
        value = payload.get(key, default)

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value != 0

        text = str(value).strip().lower()

        if text in {"true", "1", "yes", "y", "on"}:
            return True

        if text in {"false", "0", "no", "n", "off"}:
            return False

        return default

    # -------------------------------------------------
    # Serialization
    # -------------------------------------------------

    def _cost_price(self, atomic_unit) -> float:
        if not atomic_unit or not atomic_unit.meta:
            return 0.0

        meta = atomic_unit.meta if isinstance(atomic_unit.meta, dict) else {}

        for key in ("cost_price", "buying_price", "unit_cost", "purchase_price"):
            try:
                value = float(meta.get(key) or 0)
                if value > 0:
                    return value
            except Exception:
                continue

        return 0.0

    def _serialize_inventory_item(self, item) -> Dict[str, Any]:
        unit = item.atomic_unit
        cost_price = self._cost_price(unit)

        status_payload = InventoryService.stock_status_for_quantity(
            quantity_on_hand=item.quantity_on_hand,
            reorder_level=item.reorder_level,
            is_active=bool(unit.is_active) if unit else True,
        )

        return {
            "inventory_item_id": item.id,
            "atomic_unit_id": item.atomic_unit_id,
            "name": unit.name if unit else None,
            "sku": unit.sku if unit else None,
            "unit_price": float(unit.unit_price or 0) if unit else 0,
            "unit_type": unit.unit_type if unit else None,
            "is_active": bool(unit.is_active) if unit else True,
            "cost_price": cost_price,
            "estimated_stock_value": cost_price * int(item.quantity_on_hand or 0),
            "quantity_on_hand": item.quantity_on_hand,
            "reorder_level": item.reorder_level,
            "stock_status": status_payload["stock_status"],
            "stock_color": status_payload["stock_color"],
            "is_sellable": status_payload["is_sellable"],
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    def _serialize_movement(self, movement) -> Dict[str, Any]:
        unit = movement.atomic_unit

        return {
            "movement_id": movement.id,
            "inventory_item_id": movement.inventory_item_id,
            "atomic_unit_id": movement.atomic_unit_id,
            "name": unit.name if unit else None,
            "sku": unit.sku if unit else None,
            "quantity_delta": movement.quantity_delta,
            "movement_type": movement.movement_type,
            "source": movement.source,
            "reference_type": movement.reference_type,
            "reference_id": movement.reference_id,
            "created_at": movement.created_at.isoformat()
            if movement.created_at
            else None,
        }

    # -------------------------------------------------
    # List inventory items
    # -------------------------------------------------

    async def list_inventory(
        self,
        request: Request,
        db: Session,
    ):
        ctx = self._ctx(request)

        try:
            items = InventoryRepository.list_items_for_branch(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
            )

            rows = [self._serialize_inventory_item(i) for i in items]

            return {
                "count": len(rows),
                "items": rows,
                "summary": {
                    "total_items": len(rows),
                    "available": sum(
                        1 for r in rows if r["stock_status"] == "available"
                    ),
                    "low_stock": sum(
                        1 for r in rows if r["stock_status"] == "low_stock"
                    ),
                    "out_of_stock": sum(
                        1 for r in rows if r["stock_status"] == "out_of_stock"
                    ),
                    "inactive": sum(
                        1 for r in rows if r["stock_status"] == "inactive"
                    ),
                    "estimated_stock_value": sum(
                        float(r["estimated_stock_value"] or 0) for r in rows
                    ),
                },
            }

        except Exception as e:
            raise APIError(
                message="Failed to list inventory",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Commerce inventory products
    # -------------------------------------------------

    async def list_inventory_products(
        self,
        request: Request,
        db: Session,
    ):
        """
        Return all active COMMERCE → Inventory atomic units for the
        Stock Products screen.

        Unlike list_inventory(), this includes products even when no
        inventory_items row exists yet. Those products return quantity 0.
        """

        ctx = self._ctx(request)

        try:
            return InventoryService.list_commerce_inventory_products(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
            )

        except Exception as e:
            print("🔥 INVENTORY PRODUCTS RAW ERROR:", repr(e))
            raise APIError(
                message="Failed to list inventory products",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Inventory movements
    # -------------------------------------------------

    async def list_movements(
        self,
        request: Request,
        atomic_unit_id: Optional[str],
        db: Session,
    ):
        ctx = self._ctx(request)

        parsed_atomic_unit_id: Optional[int] = None

        if atomic_unit_id:
            try:
                parsed_atomic_unit_id = int(atomic_unit_id)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="atomic_unit_id must be an integer",
                )

        try:
            movements = InventoryRepository.list_movements(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                atomic_unit_id=parsed_atomic_unit_id,
                limit=200,
            )

            rows = [self._serialize_movement(m) for m in movements]

            return {
                "count": len(rows),
                "items": rows,
            }

        except Exception as e:
            raise APIError(
                message="Failed to list inventory movements",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Stock status
    # -------------------------------------------------

    async def stock_status(
        self,
        request: Request,
        atomic_unit_id: int,
        db: Session,
    ):
        ctx = self._ctx(request)

        try:
            status_payload = InventoryService.get_stock_status(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                atomic_unit_id=atomic_unit_id,
            )

            return {
                "atomic_unit_id": atomic_unit_id,
                **status_payload,
            }

        except Exception as e:
            raise APIError(
                message="Failed to get stock status",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Stock in
    # -------------------------------------------------

    async def stock_in(
        self,
        request: Request,
        payload: dict,
        db: Session,
    ):
        ctx = self._ctx(request)

        atomic_unit_id = self._int_payload(payload, "atomic_unit_id")
        quantity = self._int_payload(payload, "quantity")
        unit_cost = self._float_payload(payload, "unit_cost", required=False)
        reorder_level = self._int_payload(
            payload,
            "reorder_level",
            required=False,
            default=None,
        )
        reference_id = self._int_payload(
            payload,
            "reference_id",
            required=False,
            default=None,
        )

        if quantity is None or quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="quantity must be greater than zero",
            )

        try:
            movement = InventoryService.stock_in(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                atomic_unit_id=atomic_unit_id,
                quantity=quantity,
                unit_cost=unit_cost,
                supplier=payload.get("supplier"),
                receipt_ref=payload.get("receipt_ref"),
                note=payload.get("note"),
                reorder_level=reorder_level,
                update_cost_price=self._bool_payload(
                    payload,
                    "update_cost_price",
                    default=True,
                ),
                reference_type=payload.get("reference_type") or "stock_in",
                reference_id=reference_id,
            )

            db.commit()
            db.refresh(movement)

            return {
                "ok": True,
                "movement": self._serialize_movement(movement),
                "stock_status": InventoryService.get_stock_status(
                    db,
                    tenant_id=ctx["tenant_id"],
                    branch_id=ctx["branch_id"],
                    atomic_unit_id=atomic_unit_id,
                ),
            }

        except ValueError as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        except Exception as e:
            db.rollback()
            raise APIError(
                message="Failed to add stock",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Manual inventory adjustment
    # -------------------------------------------------

    async def adjust_inventory(
        self,
        request: Request,
        payload: dict,
        db: Session,
    ):
        ctx = self._ctx(request)

        atomic_unit_id = self._int_payload(payload, "atomic_unit_id")
        quantity_delta = self._int_payload(payload, "quantity_delta")
        reference_id = self._int_payload(
            payload,
            "reference_id",
            required=False,
            default=None,
        )

        allow_negative = self._bool_payload(
            payload,
            "allow_negative",
            default=False,
        )

        if quantity_delta == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="quantity_delta cannot be zero",
            )

        try:
            movement = InventoryService.adjust_inventory(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                atomic_unit_id=atomic_unit_id,
                quantity_delta=quantity_delta,
                source=payload.get("source") or "manual",
                note=payload.get("note"),
                allow_negative=allow_negative,
                reference_type=payload.get("reference_type") or "manual",
                reference_id=reference_id,
            )

            db.commit()
            db.refresh(movement)

            return {
                "ok": True,
                "movement": self._serialize_movement(movement),
                "stock_status": InventoryService.get_stock_status(
                    db,
                    tenant_id=ctx["tenant_id"],
                    branch_id=ctx["branch_id"],
                    atomic_unit_id=atomic_unit_id,
                ),
            }

        except ValueError as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        except Exception as e:
            db.rollback()
            raise APIError(
                message="Failed to adjust inventory",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e