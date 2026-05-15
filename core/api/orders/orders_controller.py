from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from core.domain.orders.service import OrderService
from core.domain.orders.repository import OrderRepository
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

        return {
            "id": order.id,
            "tenant_id": order.tenant_id,
            "branch_id": order.branch_id,

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