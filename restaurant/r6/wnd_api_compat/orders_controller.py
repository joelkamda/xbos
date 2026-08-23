from fastapi import Request, HTTPException
from datetime import datetime
import json
import os
from pathlib import Path
from sqlalchemy.orm import Session, selectinload

from core.domain.orders.service import OrderService
from core.domain.orders.repository import OrderRepository
from core.domain.orders.models import Order
from core.domain.sales.models import Sale
from core.domain.taxonomy.models import AtomicUnitTaxonomy, TaxonomyNode
from core.users.user_model import User


# =====================================================
# WND V1 FULFILLMENT ROUTING RULES
# =====================================================

KITCHEN_ROUTE_NAMES = {
    "MAIN DISH",
    "BREAKFAST",
    "COMPLEMENT",
    "DESERT",
    "DESSERT",
    "HOT DRINKS",
    "FOOD",
    "KITCHEN",
    "PREP",
}

NON_KITCHEN_ROUTE_NAMES = {
    "BEER",
    "SOFT DRINKS",
    "ENERGY DRINKS",
    "WHISKY",
    "WHISKEY",
    "WINE",
    "CHAMPAGNE",
    "LIQUOR",
    "CIGARETTES",
    "SHISHA",
}


class OrdersController:

    # =====================================================
    # CONTEXT
    # =====================================================

    def _ctx(self, request: Request):
        ctx = getattr(request.state, "user", None)

        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(status_code=401, detail="Missing auth context")

        return {
            "tenant_id": int(ctx["tenant_id"]),
            "branch_id": int(ctx["branch_id"]),
            "user_id": int(ctx["user_id"]),
            "role": ctx.get("role"),
        }

    # =====================================================
    # USER / AUTHOR HELPERS
    # =====================================================

    def _user_display_name(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int | None,
    ) -> str | None:
        if not user_id:
            return None

        user = (
            db.query(User)
            .filter(
                User.id == user_id,
                User.tenant_id == tenant_id,
            )
            .first()
        )

        if not user:
            return None

        return user.full_name or user.username or f"User #{user.id}"

    # =====================================================
    # TAXONOMY / FULFILLMENT HELPERS
    # =====================================================

    def _taxonomy_node(self, db: Session, tenant_id: int, node_id: int):
        return (
            db.query(TaxonomyNode)
            .filter(
                TaxonomyNode.id == node_id,
                TaxonomyNode.tenant_id == tenant_id,
                TaxonomyNode.is_active.is_(True),
            )
            .first()
        )

    def _taxonomy_path_for_atomic_unit(
        self,
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
    ) -> dict:
        """
        Returns best-effort taxonomy path for an atomic unit.

        Output shape:
        {
          "domain": "Inventory",
          "category": "MAIN DISH",
          "subcategory": "SAUCE",
          "names": ["Inventory", "MAIN DISH", "SAUCE"]
        }
        """

        mapped_rows = (
            db.query(AtomicUnitTaxonomy)
            .filter(AtomicUnitTaxonomy.atomic_unit_id == atomic_unit_id)
            .all()
        )

        if not mapped_rows:
            return {
                "domain": None,
                "category": None,
                "subcategory": None,
                "names": [],
            }

        best_path = {
            "domain": None,
            "category": None,
            "subcategory": None,
            "names": [],
        }

        for mapping in mapped_rows:
            node = self._taxonomy_node(
                db,
                tenant_id=tenant_id,
                node_id=mapping.taxonomy_node_id,
            )

            if not node:
                continue

            nodes = []
            cursor = node
            guard = 0

            while cursor and guard < 10:
                nodes.append(cursor)

                if not cursor.parent_id:
                    break

                cursor = self._taxonomy_node(
                    db,
                    tenant_id=tenant_id,
                    node_id=cursor.parent_id,
                )

                guard += 1

            nodes = list(reversed(nodes))

            path = {
                "domain": None,
                "category": None,
                "subcategory": None,
                "names": [],
            }

            for n in nodes:
                name = str(n.name or "").strip()

                if name:
                    path["names"].append(name)

                level = str(n.semantic_level or "").lower()

                if level == "domain":
                    path["domain"] = name
                elif level == "category":
                    path["category"] = name
                elif level == "subcategory":
                    path["subcategory"] = name

            names_upper = {str(x).upper() for x in path["names"]}

            if "INVENTORY" in names_upper:
                return path

            if path["names"] and not best_path["names"]:
                best_path = path

        return best_path

    def _fulfillment_payload_for_item(
        self,
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
        stored_status: str | None = None,
    ) -> dict:
        """
        Converts taxonomy path into routing metadata.

        Important:
        - Routing can still be taxonomy-derived.
        - Status must come from DB when available.
        """

        path = self._taxonomy_path_for_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        names_upper = {
            str(name or "").strip().upper()
            for name in path.get("names", [])
            if str(name or "").strip()
        }

        category_upper = str(path.get("category") or "").strip().upper()
        subcategory_upper = str(path.get("subcategory") or "").strip().upper()

        has_explicit_non_kitchen = bool(
            names_upper.intersection(NON_KITCHEN_ROUTE_NAMES)
        )

        has_kitchen_match = bool(
            names_upper.intersection(KITCHEN_ROUTE_NAMES)
            or category_upper in KITCHEN_ROUTE_NAMES
            or subcategory_upper in KITCHEN_ROUTE_NAMES
        )

        requires_fulfillment = bool(
            has_kitchen_match and not has_explicit_non_kitchen
        )

        final_status = str(stored_status or "waiting").strip().lower()

        if requires_fulfillment:
            return {
                "requires_fulfillment": True,
                "requires_preparation": True,
                "fulfillment_queue": "kitchen",
                "fulfillment_station": "kitchen",
                "fulfillment_status": final_status,
                "show_queue_qualifier": True,
                "commerce_category": path.get("category"),
                "commerce_subcategory": path.get("subcategory"),
            }

        return {
            "requires_fulfillment": False,
            "requires_preparation": False,
            "fulfillment_queue": None,
            "fulfillment_station": None,
            "fulfillment_status": final_status if final_status != "waiting" else None,
            "show_queue_qualifier": False,
            "commerce_category": path.get("category"),
            "commerce_subcategory": path.get("subcategory"),
        }

    # =====================================================
    # SERIALIZATION
    # =====================================================

    def _serialize_modifier(self, modifier):
        return {
            "id": modifier.id,
            "modifier_type": modifier.modifier_type,
            "type": modifier.modifier_type,
            "name_snapshot": modifier.name_snapshot,
            "name": modifier.name_snapshot,
            "price_delta": float(modifier.price_delta or 0),
            "quantity": modifier.quantity or 1,
        }

    def _serialize_order_item(
        self,
        item,
        *,
        db: Session,
        tenant_id: int,
    ):
        stored_status = getattr(item, "fulfillment_status", None)

        fulfillment = self._fulfillment_payload_for_item(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=item.atomic_unit_id,
            stored_status=stored_status,
        )

        modifiers = [
            self._serialize_modifier(modifier)
            for modifier in (getattr(item, "modifiers", None) or [])
        ]

        return {
            "id": item.id,
            "order_item_id": item.id,
            "atomic_unit_id": item.atomic_unit_id,
            "name_snapshot": item.name_snapshot,
            "name": item.name_snapshot,
            "unit_price": float(item.unit_price or 0),
            "quantity": item.quantity,
            "line_total": float(item.line_total or 0),
            "modifiers": modifiers,
            "side": next(
                (
                    m["name_snapshot"]
                    for m in modifiers
                    if str(m.get("modifier_type") or "").lower() == "side"
                ),
                None,
            ),
            "fulfilled_at": item.fulfilled_at.isoformat()
            if getattr(item, "fulfilled_at", None)
            else None,
            "fulfilled_by_user_id": getattr(item, "fulfilled_by_user_id", None),
            **fulfillment,
        }

    def _serialize_order(
        self,
        order,
        *,
        db: Session,
    ):
        created_by_user_id = getattr(order, "created_by_user_id", None)
        created_by_name = self._user_display_name(
            db,
            tenant_id=order.tenant_id,
            user_id=created_by_user_id,
        )

        fulfillment_mode = getattr(order, "fulfillment_mode", None)

        return {
            "id": order.id,
            "tenant_id": order.tenant_id,
            "branch_id": order.branch_id,
            "fulfillment_mode": fulfillment_mode,
            # Compatibility alias for the existing POS payload vocabulary.
            "order_type": fulfillment_mode,

            # Commission-safe author/originator fields.
            "created_by_user_id": created_by_user_id,
            "created_by_name": created_by_name,
            "served_by_name": created_by_name,

            "status": order.status,
            "subtotal": float(order.subtotal or 0),
            "total": float(order.total or 0),
            "created_at": order.created_at.isoformat()
            if order.created_at
            else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "items": [
                self._serialize_order_item(
                    item,
                    db=db,
                    tenant_id=order.tenant_id,
                )
                for item in (order.items or [])
            ],
        }

    # =====================================================
    # ORDER FULFILLMENT MODE LOOKUPS
    # =====================================================

    async def sale_fulfillment_modes(
        self,
        request: Request,
        *,
        db: Session,
        limit: int = 200,
    ):
        """
        Returns order fulfillment mode keyed by sale id.

        This keeps fulfillment as order truth while allowing Sales Archive
        to display/filter TAKEAWAY without duplicating the field on sales.
        """
        ctx = self._ctx(request)

        rows = (
            db.query(
                Sale.id,
                Sale.order_id,
                Order.fulfillment_mode,
            )
            .outerjoin(
                Order,
                Order.id == Sale.order_id,
            )
            .filter(
                Sale.tenant_id == ctx["tenant_id"],
                Sale.branch_id == ctx["branch_id"],
            )
            .order_by(Sale.created_at.desc())
            .limit(max(1, min(int(limit or 200), 500)))
            .all()
        )

        return {
            "modes_by_sale_id": {
                str(int(sale_id)): fulfillment_mode
                for sale_id, _order_id, fulfillment_mode in rows
            },
            "tracked_values": ["DINE_IN", "TAKEAWAY", "DELIVERY"],
            "historical_null_means": "UNSPECIFIED",
        }

    # =====================================================
    # TRACK A KITCHEN HISTORY BRIDGE
    # =====================================================

    def _kitchen_history_path(self) -> Path:
        state_dir = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "XBOS"
        )
        return state_dir / os.environ.get(
            "XBOS_KITCHEN_HISTORY_FILE",
            "kitchen_history_xbos.jsonl",
        )

    def _kitchen_window_datetime(
        self,
        value: str,
        *,
        label: str,
    ) -> datetime:
        raw = str(value or "").strip()

        if not raw:
            raise HTTPException(
                status_code=400,
                detail=f"Missing {label}",
            )

        try:
            parsed = datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {label}",
            )

        if parsed.tzinfo is None:
            raise HTTPException(
                status_code=400,
                detail=f"{label} must include timezone offset",
            )

        return parsed

    def _kitchen_history_rows(
        self,
        *,
        tenant_id: int,
        branch_id: int,
        start_dt: datetime,
        end_dt: datetime,
        limit: int | None,
    ) -> list[dict]:
        path = self._kitchen_history_path()

        if not path.is_file():
            return []

        rows = []

        try:
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to read kitchen history: {exc}",
            )

        for line in lines:
            raw = str(line or "").strip()

            if not raw:
                continue

            try:
                row = json.loads(raw)
            except Exception:
                # Concurrent append can briefly expose a partial final line.
                continue

            if int(row.get("tenant_id") or 0) != int(tenant_id):
                continue

            if int(row.get("branch_id") or 0) != int(branch_id):
                continue

            occurred_raw = str(row.get("occurred_at") or "").strip()

            try:
                occurred_at = datetime.fromisoformat(
                    occurred_raw.replace("Z", "+00:00")
                )
            except Exception:
                continue

            if occurred_at.tzinfo is None:
                continue

            if not (start_dt <= occurred_at < end_dt):
                continue

            rows.append(row)

        rows.sort(
            key=lambda row: str(row.get("occurred_at") or ""),
            reverse=True,
        )

        if limit is not None:
            return rows[: max(1, min(int(limit), 2000))]

        return rows

    async def kitchen_history(
        self,
        request: Request,
        *,
        start: str,
        end: str,
        limit: int = 500,
    ):
        ctx = self._ctx(request)
        start_dt = self._kitchen_window_datetime(
            start,
            label="start",
        )
        end_dt = self._kitchen_window_datetime(
            end,
            label="end",
        )

        if end_dt <= start_dt:
            raise HTTPException(
                status_code=400,
                detail="end must be after start",
            )

        rows = self._kitchen_history_rows(
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start_dt=start_dt,
            end_dt=end_dt,
            limit=limit,
        )

        event_counts = {}
        printed_lines = 0

        for row in rows:
            event = str(row.get("event") or "UNKNOWN")
            event_counts[event] = event_counts.get(event, 0) + 1
            printed_lines += len(row.get("items") or [])

        return {
            "start": start,
            "end": end,
            "history_file_present": self._kitchen_history_path().is_file(),
            "rows": rows,
            "summary": {
                "events": len(rows),
                "printed_lines": printed_lines,
                "event_counts": event_counts,
            },
            "note": (
                "Structured bon history begins when the Track A history "
                "bridge is activated; earlier print chronology is not invented."
            ),
        }

    async def kitchen_item_summary(
        self,
        request: Request,
        *,
        start: str,
        end: str,
        db: Session,
    ):
        ctx = self._ctx(request)
        start_dt = self._kitchen_window_datetime(
            start,
            label="start",
        )
        end_dt = self._kitchen_window_datetime(
            end,
            label="end",
        )

        if end_dt <= start_dt:
            raise HTTPException(
                status_code=400,
                detail="end must be after start",
            )

        history_rows = self._kitchen_history_rows(
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start_dt=start_dt,
            end_dt=end_dt,
            limit=None,
        )

        summary_rows: dict[str, dict] = {}

        def item_key(
            atomic_unit_id,
            name_snapshot,
        ) -> str:
            if atomic_unit_id is not None:
                return f"au:{atomic_unit_id}"

            normalized = " ".join(
                str(name_snapshot or "ITEM").strip().upper().split()
            )
            return f"name:{normalized}"

        def ensure_row(
            atomic_unit_id,
            name_snapshot,
        ) -> dict:
            key = item_key(
                atomic_unit_id,
                name_snapshot,
            )

            if key not in summary_rows:
                summary_rows[key] = {
                    "key": key,
                    "atomic_unit_id": atomic_unit_id,
                    "name_snapshot": str(
                        name_snapshot or "ITEM"
                    ),
                    "ordered_qty": 0,
                    "cancelled_qty": 0,
                    "net_kitchen_qty": 0,
                    "sold_qty": 0,
                    "sales_xaf": 0.0,
                    "kitchen_minus_sold_qty": 0,
                    "bon_events": 0,
                }

            return summary_rows[key]

        for event_row in history_rows:
            seen_in_event = set()

            for item in event_row.get("items") or []:
                quantity = int(item.get("quantity") or 0)

                if quantity <= 0:
                    continue

                row = ensure_row(
                    item.get("atomic_unit_id"),
                    item.get("name_snapshot"),
                )

                direction = str(
                    item.get("direction") or ""
                ).strip().lower()

                if direction == "add":
                    row["ordered_qty"] += quantity
                elif direction == "cancel":
                    row["cancelled_qty"] += quantity

                if row["key"] not in seen_in_event:
                    row["bon_events"] += 1
                    seen_in_event.add(row["key"])

        sales = (
            db.query(Sale)
            .options(selectinload(Sale.items))
            .filter(
                Sale.tenant_id == ctx["tenant_id"],
                Sale.branch_id == ctx["branch_id"],
                Sale.created_at >= start_dt,
                Sale.created_at < end_dt,
                Sale.status != "cancelled",
            )
            .all()
        )

        route_cache: dict[int, bool] = {}

        for sale in sales:
            for item in sale.items or []:
                atomic_unit_id = int(item.atomic_unit_id)

                if atomic_unit_id not in route_cache:
                    route = self._fulfillment_payload_for_item(
                        db,
                        tenant_id=ctx["tenant_id"],
                        atomic_unit_id=atomic_unit_id,
                    )
                    route_cache[atomic_unit_id] = bool(
                        route.get("requires_fulfillment")
                    )

                if not route_cache[atomic_unit_id]:
                    continue

                row = ensure_row(
                    atomic_unit_id,
                    item.name_snapshot,
                )
                row["sold_qty"] += int(item.quantity or 0)
                row["sales_xaf"] += float(item.line_total or 0)

        rows = []

        for row in summary_rows.values():
            row["net_kitchen_qty"] = (
                int(row["ordered_qty"])
                - int(row["cancelled_qty"])
            )
            row["kitchen_minus_sold_qty"] = (
                int(row["net_kitchen_qty"])
                - int(row["sold_qty"])
            )
            rows.append(row)

        rows.sort(
            key=lambda row: (
                -int(row["sold_qty"]),
                -int(row["net_kitchen_qty"]),
                str(row["name_snapshot"]).upper(),
            )
        )

        return {
            "start": start,
            "end": end,
            "history_file_present": self._kitchen_history_path().is_file(),
            "rows": rows,
            "summary": {
                "ordered_qty": sum(
                    int(row["ordered_qty"])
                    for row in rows
                ),
                "cancelled_qty": sum(
                    int(row["cancelled_qty"])
                    for row in rows
                ),
                "net_kitchen_qty": sum(
                    int(row["net_kitchen_qty"])
                    for row in rows
                ),
                "sold_qty": sum(
                    int(row["sold_qty"])
                    for row in rows
                ),
                "sales_xaf": sum(
                    float(row["sales_xaf"])
                    for row in rows
                ),
                "kitchen_minus_sold_qty": sum(
                    int(row["kitchen_minus_sold_qty"])
                    for row in rows
                ),
            },
            "source_note": (
                "Ordered/cancelled/net kitchen quantities come from structured "
                "bon events captured after bridge activation. Sold quantity and "
                "sales XAF come from existing sale_items commercial truth."
            ),
        }

    # =====================================================
    # CREATE ORDER
    # =====================================================

    async def create_order(self, request: Request, payload: dict, db: Session):
        ctx = self._ctx(request)

        try:
            order = OrderService.create_order(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                created_by_user_id=ctx["user_id"],
                payload=payload,
            )

            order = OrderRepository.get_by_id(db, order.id)

            return self._serialize_order(order, db=db)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # =====================================================
    # LIST PENDING ORDERS
    # =====================================================

    async def list_orders(self, request: Request, db: Session):
        ctx = self._ctx(request)

        orders = OrderRepository.list_pending(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
        )

        return [
            self._serialize_order(order, db=db)
            for order in orders
        ]

    # =====================================================
    # GET SINGLE ORDER
    # =====================================================

    async def get_order(self, request: Request, order_id: int, db: Session):
        ctx = self._ctx(request)

        order = OrderRepository.get_by_id(db, order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.tenant_id != ctx["tenant_id"]:
            raise HTTPException(status_code=403, detail="Unauthorized")

        if order.branch_id != ctx["branch_id"]:
            raise HTTPException(status_code=403, detail="Unauthorized")

        return self._serialize_order(order, db=db)

    # =====================================================
    # UPDATE PENDING ORDER
    # =====================================================

    async def update_order(
        self,
        request: Request,
        order_id: int,
        payload: dict,
        db: Session,
    ):
        ctx = self._ctx(request)

        try:
            order = OrderService.update_order(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                order_id=order_id,
                payload=payload,
            )

            order = OrderRepository.get_by_id(db, order.id)

            response = self._serialize_order(order, db=db)
            response["message"] = "Order updated successfully"

            return response

        except ValueError as e:
            detail = str(e)

            if detail == "Order not found":
                raise HTTPException(status_code=404, detail=detail)

            raise HTTPException(status_code=400, detail=detail)

    # =====================================================
    # UPDATE ITEM FULFILLMENT STATUS
    # =====================================================

    async def update_item_fulfillment_status(
        self,
        request: Request,
        order_id: int,
        order_item_id: int,
        payload: dict,
        db: Session,
    ):
        ctx = self._ctx(request)

        status = payload.get("status")

        if not status:
            raise HTTPException(status_code=400, detail="Missing status")

        try:
            item = OrderService.update_item_fulfillment_status(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                order_id=order_id,
                order_item_id=order_item_id,
                status=status,
                user_id=ctx.get("user_id"),
            )

            return self._serialize_order_item(
                item,
                db=db,
                tenant_id=ctx["tenant_id"],
            ) | {
                "order_id": item.order_id,
                "message": "Item fulfillment status updated successfully",
            }

        except ValueError as e:
            detail = str(e)

            if detail in {"Order not found", "Order item not found"}:
                raise HTTPException(status_code=404, detail=detail)

            raise HTTPException(status_code=400, detail=detail)

    # =====================================================
    # CANCEL PENDING ORDER
    # =====================================================

    async def cancel_order(
        self,
        request: Request,
        order_id: int,
        db: Session,
    ):
        ctx = self._ctx(request)

        try:
            order = OrderService.cancel_order(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                order_id=order_id,
            )

            return {
                "id": order.id,
                "status": order.status,
                "message": "Order cancelled successfully",
            }

        except ValueError as e:
            detail = str(e)

            if detail == "Order not found":
                raise HTTPException(status_code=404, detail=detail)

            raise HTTPException(status_code=400, detail=detail)