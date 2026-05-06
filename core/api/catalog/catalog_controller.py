from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.catalog.service import CatalogService
from core.domain.inventory.service import InventoryService
from core.errors.api_error import APIError


class CatalogController:
    """
    HTTP controller for Catalog / Atomic Units.

    Responsibilities:
    - Extract tenant / branch context
    - Delegate catalog lookup to CatalogService
    - Enrich POS catalog items with inventory status
    - Format responses
    - No heavy business logic
    """

    def __init__(self):
        pass

    # -------------------------------------------------
    # Context
    # -------------------------------------------------

    def _ctx(self, request: Request):
        """
        Supports both styles:
        - request.state.user = { tenant_id, branch_id, ... }
        - request.state.tenant_id / request.state.branch_id

        The current auth middleware injects request.state.user.
        """

        user = getattr(request.state, "user", None)

        if isinstance(user, dict):
            tenant_id = user.get("tenant_id")
            branch_id = user.get("branch_id")
        else:
            tenant_id = getattr(request.state, "tenant_id", None)
            branch_id = getattr(request.state, "branch_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        return {
            "tenant_id": int(tenant_id),
            "branch_id": int(branch_id) if branch_id else None,
        }

    # -------------------------------------------------
    # Serialization
    # -------------------------------------------------

    def _base_unit_payload(self, unit):
        return {
            "id": unit.id,
            "name": unit.name,
            "unit_price": float(unit.unit_price or 0),
            "price": float(unit.unit_price or 0),
            "sku": unit.sku,
            "unit_type": unit.unit_type,
            "is_active": bool(unit.is_active),
            "meta": unit.meta if isinstance(unit.meta, dict) else {},
        }

    def _serialize_unit_with_inventory(
        self,
        *,
        unit,
        db: Session,
        tenant_id: int,
        branch_id: int | None,
    ):
        """
        POS/backoffice-safe atomic unit payload.

        If branch_id exists, enrich with live stock status.
        If branch_id is missing, return catalog-only fields with safe inventory defaults.
        """

        payload = self._base_unit_payload(unit)

        if not branch_id:
            payload.update(
                {
                    "quantity_on_hand": None,
                    "reorder_level": None,
                    "stock_status": "unknown",
                    "stock_color": "gray",
                    "stock_tracked": None,
                    "inventory_family": None,
                    "commerce_category": None,
                    "commerce_subcategory": None,
                    "allow_negative_stock": None,
                    "disable_when_out": None,
                    "disable_sale": False,
                    "cost_mode": None,
                    "is_sellable": bool(unit.is_active),
                    "mapping_warnings": [],
                }
            )
            return payload

        stock_payload = InventoryService.get_stock_status(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=unit.id,
        )

        payload.update(stock_payload)

        # Frontend compatibility:
        # Some screens read "price", others read "unit_price".
        payload["price"] = payload["unit_price"]

        # Final POS sale button rule:
        # - inactive unit cannot be sold
        # - disable_sale from inventory profile/status blocks POS click
        payload["disable_sale"] = bool(
            payload.get("disable_sale") or not bool(unit.is_active)
        )

        payload["is_sellable"] = bool(
            bool(unit.is_active) and not payload["disable_sale"]
        )

        return payload

    # -------------------------------------------------
    # Catalog summary: categories + subcategories
    # -------------------------------------------------

    async def catalog_summary(
        self,
        request: Request,
        db: Session,
    ):
        ctx = self._ctx(request)
        tenant_id = ctx["tenant_id"]

        try:
            rows = CatalogService.catalog_summary(
                db,
                tenant_id=tenant_id,
            )

            categories = {}

            for r in rows:
                if not r.category_id:
                    continue

                category = categories.setdefault(
                    r.category_id,
                    {
                        "id": r.category_id,
                        "name": r.category_name,
                        "subcategories": [],
                    },
                )

                if r.subcategory_id:
                    category["subcategories"].append(
                        {
                            "id": r.subcategory_id,
                            "name": r.subcategory_name,
                        }
                    )

            return {
                "categories": list(categories.values())
            }

        except Exception as e:
            print("🔥 CATALOG SUMMARY RAW ERROR:", repr(e))
            raise APIError("CATALOG_SUMMARY_FAILED") from e

    # -------------------------------------------------
    # List by subcategory: POS-optimized
    # -------------------------------------------------

    async def list_by_subcategory(
        self,
        request: Request,
        subcategory_id: int,
        db: Session,
    ):
        ctx = self._ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        try:
            units = CatalogService.list_by_subcategory(
                db,
                tenant_id=tenant_id,
                subcategory_id=subcategory_id,
                active_only=True,
            )

            return {
                "items": [
                    self._serialize_unit_with_inventory(
                        unit=u,
                        db=db,
                        tenant_id=tenant_id,
                        branch_id=branch_id,
                    )
                    for u in units
                ]
            }

        except Exception as e:
            print("🔥 CATALOG SUBCATEGORY RAW ERROR:", repr(e))
            raise APIError("CATALOG_SUBCATEGORY_LIST_FAILED") from e

    # -------------------------------------------------
    # List all atomic units: admin/backoffice
    # -------------------------------------------------

    async def list_atomic_units(
        self,
        request: Request,
        db: Session,
    ):
        ctx = self._ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        try:
            units = CatalogService.list_all(
                db,
                tenant_id=tenant_id,
                active_only=True,
            )

            return [
                self._serialize_unit_with_inventory(
                    unit=u,
                    db=db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                )
                for u in units
            ]

        except Exception as e:
            print("🔥 CATALOG LIST RAW ERROR:", repr(e))
            raise APIError("CATALOG_LIST_FAILED") from e

    # -------------------------------------------------
    # List by taxonomy: generic
    # -------------------------------------------------

    async def list_by_taxonomy(
        self,
        request: Request,
        taxonomy_node_id: int,
        db: Session,
    ):
        ctx = self._ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        try:
            units = CatalogService.list_by_taxonomy(
                db,
                tenant_id=tenant_id,
                taxonomy_node_id=taxonomy_node_id,
                active_only=True,
            )

            return [
                self._serialize_unit_with_inventory(
                    unit=u,
                    db=db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                )
                for u in units
            ]

        except Exception as e:
            print("🔥 CATALOG TAXONOMY RAW ERROR:", repr(e))
            raise APIError("CATALOG_TAXONOMY_LIST_FAILED") from e

    # -------------------------------------------------
    # Search
    # -------------------------------------------------

    async def search(
        self,
        request: Request,
        q: str,
        db: Session,
    ):
        ctx = self._ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        if not q:
            return []

        try:
            units = CatalogService.search(
                db,
                tenant_id=tenant_id,
                query=q,
                active_only=True,
            )

            return [
                self._serialize_unit_with_inventory(
                    unit=u,
                    db=db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                )
                for u in units
            ]

        except Exception as e:
            print("🔥 CATALOG SEARCH RAW ERROR:", repr(e))
            raise APIError("CATALOG_SEARCH_FAILED") from e