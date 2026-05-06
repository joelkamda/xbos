from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

from fastapi import Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.accounting.reports import AccountingReportsService
from core.domain.accounting.emitter import FinancialEventEmitter
from core.domain.taxonomy.models import (
    TaxonomyNode,
    AtomicUnit,
)
from core.domain.catalog.repository import AtomicUnitRepository


# ============================================================
# UTILITIES
# ============================================================

def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    return datetime.fromisoformat(v)


def _d(v: Any) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _ctx(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "user", None)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing user/session context",
        )

    if not user.get("tenant_id") or not user.get("branch_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant or branch context",
        )

    return user


def _safe_channel(value: Optional[str]) -> str:
    channel = str(value or "").strip().lower()

    allowed = {"cash", "mtn", "orange", "xafpay", "bank"}

    if channel not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid accounting channel: {value}",
        )

    return channel


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _time_str(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%I:%M %p")


def _event_row_type(event_type: str) -> str:
    if event_type in {
        "SALE_REVENUE_GROSS",
        "TIP_REVENUE",
        "SERVICE_REVENUE",
        "OTHER_INCOME",
    }:
        return "income"

    if event_type in {
        "DISCOUNT_APPLIED",
        "COMPLIMENTARY_APPLIED",
        "EXPENSE_POSTED",
        "COGS_RECOGNIZED",
        "REFUND_PAID",
    }:
        return "expense"

    return "movement"


def _entry_label(log) -> str:
    event_type = log.event_type
    meta = log.meta or {}

    if event_type == "SALE_REVENUE_GROSS":
        return "Sales Revenue · Restaurant"

    if event_type == "TIP_REVENUE":
        return "Other Income · Tips / Service"

    if event_type == "SERVICE_REVENUE":
        return meta.get("category_name") or "Service Revenue"

    if event_type == "OTHER_INCOME":
        category = meta.get("category_name")
        item = meta.get("item_name") or meta.get("subcategory_name")
        if category and item:
            return f"{category} · {item}"
        if category:
            return category
        return "Other Income"

    if event_type == "DISCOUNT_APPLIED":
        label = meta.get("display_label") or meta.get("discount_reason") or "Discount"
        return f"Discount · {label}"

    if event_type == "COMPLIMENTARY_APPLIED":
        label = meta.get("display_label") or meta.get("complimentary_reason") or "Complimentary"
        return f"Complimentary · {label}"

    if event_type == "EXPENSE_POSTED":
        category = meta.get("category_name")
        item = meta.get("item_name") or meta.get("subcategory_name")
        if category and item:
            return f"{category} · {item}"
        if category:
            return category
        return "Expense"

    if event_type == "COGS_RECOGNIZED":
        return "COGS Recognized"

    if event_type == "PAYMENT_RECEIVED":
        return "Customer Payment"

    if event_type == "CHANGE_RETURNED":
        return "Change Returned"

    if event_type == "CASH_MOVE":
        src = meta.get("source_channel") or meta.get("from") or "Source"
        dst = meta.get("target_channel") or meta.get("to") or "Target"
        return f"{str(src).upper()} → {str(dst).upper()}"

    if event_type == "DEBT_CREATED":
        return "Customer Debt"

    if event_type == "DEBT_REPAYMENT":
        return "Debt Repayment"

    if event_type == "STORE_CREDIT_CREATED":
        return "Store Credit / Change Owed"

    if event_type == "REFUND_PAID":
        return "Refund Paid"

    return str(event_type or "Event").replace("_", " ").title()


def _serialize_log(log) -> Dict[str, Any]:
    """
    Safe local serializer for newly-created TreasuryLog rows.

    Avoids relying on AccountingReportsService internals during create calls.
    Includes taxonomy_node_id so frontend can immediately confirm classification.
    """

    if not log:
        return {}

    timestamp = log.occurred_at or log.created_at

    return {
        "id": log.id,
        "time": _time_str(timestamp),
        "type": _event_row_type(log.event_type),
        "entry": _entry_label(log),
        "event_type": log.event_type,
        "direction": log.direction,
        "amount": _f(log.amount),
        "currency": log.currency,
        "channel": log.channel,
        "reference_type": log.reference_type,
        "reference_id": log.reference_id,
        "taxonomy_node_id": log.taxonomy_node_id,
        "details": log.meta or {},
    }


def _serialize_taxonomy_node(node: TaxonomyNode) -> Dict[str, Any]:
    return {
        "id": node.id,
        "tenant_id": node.tenant_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "taxonomy_type": node.taxonomy_type,
        "semantic_level": node.semantic_level,
        "sort_order": node.sort_order,
        "is_active": node.is_active,
    }


def _serialize_atomic_unit(unit: AtomicUnit) -> Dict[str, Any]:
    return {
        "id": unit.id,
        "tenant_id": unit.tenant_id,
        "name": unit.name,
        "sku": unit.sku,
        "unit_price": float(unit.unit_price or 0),
        "unit_type": unit.unit_type,
        "is_active": unit.is_active,
        "meta": unit.meta or {},
    }


# ============================================================
# CONTROLLER
# ============================================================

class AccountingController:

    # ========================================================
    # REPORT READS
    # ========================================================

    @staticmethod
    def daily(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.daily_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def income(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.income_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def expenses(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.expenses_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def cash_moves(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.cash_moves_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def debt(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.debt_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def reconciliation(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ):
        ctx = _ctx(request)

        return AccountingReportsService.reconciliation_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    # ========================================================
    # TAXONOMY HELPERS
    # ========================================================

    @staticmethod
    def _get_domain(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_type: str,
        domain_name: str,
    ) -> TaxonomyNode:
        stmt = (
            select(TaxonomyNode)
            .where(
                TaxonomyNode.tenant_id == tenant_id,
                TaxonomyNode.taxonomy_type == taxonomy_type,
                TaxonomyNode.semantic_level == "domain",
                TaxonomyNode.name == domain_name,
                TaxonomyNode.is_active.is_(True),
            )
            .limit(1)
        )

        node = db.execute(stmt).scalar_one_or_none()

        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Taxonomy domain not found: {taxonomy_type} → {domain_name}",
            )

        return node

    @staticmethod
    def _get_node(
        db: Session,
        *,
        tenant_id: int,
        node_id: int,
    ) -> TaxonomyNode:
        stmt = (
            select(TaxonomyNode)
            .where(
                TaxonomyNode.tenant_id == tenant_id,
                TaxonomyNode.id == node_id,
                TaxonomyNode.is_active.is_(True),
            )
            .limit(1)
        )

        node = db.execute(stmt).scalar_one_or_none()

        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Taxonomy node not found: {node_id}",
            )

        return node

    @staticmethod
    def _children(
        db: Session,
        *,
        tenant_id: int,
        parent_id: int,
        semantic_level: Optional[str] = None,
    ) -> List[TaxonomyNode]:
        stmt = (
            select(TaxonomyNode)
            .where(
                TaxonomyNode.tenant_id == tenant_id,
                TaxonomyNode.parent_id == parent_id,
                TaxonomyNode.is_active.is_(True),
            )
        )

        if semantic_level:
            stmt = stmt.where(TaxonomyNode.semantic_level == semantic_level)

        stmt = stmt.order_by(TaxonomyNode.sort_order.asc(), TaxonomyNode.name.asc())

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def _validate_finance_path(
        db: Session,
        *,
        tenant_id: int,
        domain_name: str,
        category_taxonomy_id: int,
        subcategory_taxonomy_id: int,
    ) -> Dict[str, TaxonomyNode]:
        domain = AccountingController._get_domain(
            db,
            tenant_id=tenant_id,
            taxonomy_type="FINANCE",
            domain_name=domain_name,
        )

        category = AccountingController._get_node(
            db,
            tenant_id=tenant_id,
            node_id=category_taxonomy_id,
        )

        if category.parent_id != domain.id or category.semantic_level != "category":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid category for FINANCE → {domain_name}",
            )

        subcategory = AccountingController._get_node(
            db,
            tenant_id=tenant_id,
            node_id=subcategory_taxonomy_id,
        )

        if (
            subcategory.parent_id != category.id
            or subcategory.semantic_level != "subcategory"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid subcategory for selected category",
            )

        return {
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
        }

    @staticmethod
    def _validate_atomic_unit(
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: Optional[int],
    ) -> Optional[AtomicUnit]:
        if not atomic_unit_id:
            return None

        unit = AtomicUnitRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        if not unit or not unit.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid atomic unit: {atomic_unit_id}",
            )

        return unit

    # ========================================================
    # ACCOUNTING MODAL TAXONOMY
    # ========================================================

    @staticmethod
    def taxonomy_tree(
        *,
        request: Request,
        db: Session,
        taxonomy_type: str,
        domain_name: str,
    ):
        ctx = _ctx(request)
        tenant_id = ctx["tenant_id"]

        domain = AccountingController._get_domain(
            db,
            tenant_id=tenant_id,
            taxonomy_type=taxonomy_type,
            domain_name=domain_name,
        )

        categories = AccountingController._children(
            db,
            tenant_id=tenant_id,
            parent_id=domain.id,
            semantic_level="category",
        )

        result_categories = []

        for category in categories:
            subcategories = AccountingController._children(
                db,
                tenant_id=tenant_id,
                parent_id=category.id,
                semantic_level="subcategory",
            )

            result_categories.append(
                {
                    **_serialize_taxonomy_node(category),
                    "subcategories": [
                        _serialize_taxonomy_node(sub) for sub in subcategories
                    ],
                }
            )

        return {
            "taxonomy_type": taxonomy_type,
            "domain": _serialize_taxonomy_node(domain),
            "categories": result_categories,
        }

    @staticmethod
    def search_items(
        *,
        request: Request,
        db: Session,
        taxonomy_node_id: Optional[int] = None,
        q: str = "",
        limit: int = 25,
    ):
        ctx = _ctx(request)
        tenant_id = ctx["tenant_id"]

        safe_limit = max(1, min(int(limit or 25), 100))
        query = (q or "").strip().lower()

        if taxonomy_node_id:
            AccountingController._get_node(
                db,
                tenant_id=tenant_id,
                node_id=taxonomy_node_id,
            )

            units = AtomicUnitRepository.list_by_taxonomy(
                db,
                tenant_id=tenant_id,
                taxonomy_node_id=taxonomy_node_id,
                active_only=True,
            )

            if query:
                units = [
                    u
                    for u in units
                    if query in (u.name or "").lower()
                    or query in (u.sku or "").lower()
                ]

            units = units[:safe_limit]

        else:
            units = AtomicUnitRepository.search(
                db,
                tenant_id=tenant_id,
                query=query,
                active_only=True,
                limit=safe_limit,
            )

        return {
            "items": [_serialize_atomic_unit(unit) for unit in units],
            "count": len(units),
        }

    # ========================================================
    # MANUAL INCOME CREATE
    # ========================================================

    @staticmethod
    def create_manual_income(
        *,
        request: Request,
        db: Session,
        payload: Dict[str, Any],
    ):
        ctx = _ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx.get("user_id")

        amount = _d(payload.get("amount"))
        channel = _safe_channel(payload.get("channel"))

        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero",
            )

        client_reference = str(payload.get("client_reference") or "").strip()
        if not client_reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_reference is required",
            )

        category_id = int(payload.get("category_taxonomy_id") or 0)
        subcategory_id = int(payload.get("subcategory_taxonomy_id") or 0)

        path = AccountingController._validate_finance_path(
            db,
            tenant_id=tenant_id,
            domain_name="Revenue",
            category_taxonomy_id=category_id,
            subcategory_taxonomy_id=subcategory_id,
        )

        atomic_unit = AccountingController._validate_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=payload.get("atomic_unit_id"),
        )

        item_name = (
            atomic_unit.name
            if atomic_unit
            else str(payload.get("item_name") or "").strip()
        )

        if not item_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specific item is required",
            )

        category = path["category"]
        subcategory = path["subcategory"]

        event_type = "OTHER_INCOME"
        if category.name == "Service Revenue":
            event_type = "SERVICE_REVENUE"

        log = FinancialEventEmitter.manual_income(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            client_reference=client_reference,
            amount=amount,
            currency=payload.get("currency") or "XAF",
            channel=channel,
            taxonomy_node_id=subcategory.id,
            event_type=event_type,
            occurred_at=_parse_dt(payload.get("occurred_at")),
            meta={
                "domain_taxonomy_id": path["domain"].id,
                "domain_name": path["domain"].name,
                "category_taxonomy_id": category.id,
                "category_name": category.name,
                "subcategory_taxonomy_id": subcategory.id,
                "subcategory_name": subcategory.name,
                "item_mode": payload.get("item_mode") or "free_text",
                "atomic_unit_id": atomic_unit.id if atomic_unit else None,
                "item_name": item_name,
                "source_name": payload.get("source_name"),
                "reference": payload.get("reference"),
                "note": payload.get("note"),
                "created_by_user_id": user_id,
            },
        )

        try:
            db.flush()
            db.commit()

            if log:
                db.refresh(log)

            return {
                "ok": True,
                "event": _serialize_log(log),
            }

        except Exception:
            db.rollback()
            raise

    # ========================================================
    # EXPENSE CREATE
    # ========================================================

    @staticmethod
    def create_expense(
        *,
        request: Request,
        db: Session,
        payload: Dict[str, Any],
    ):
        ctx = _ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx.get("user_id")

        amount = _d(payload.get("amount"))
        channel = _safe_channel(payload.get("channel"))

        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero",
            )

        client_reference = str(payload.get("client_reference") or "").strip()
        if not client_reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_reference is required",
            )

        category_id = int(payload.get("category_taxonomy_id") or 0)
        subcategory_id = int(payload.get("subcategory_taxonomy_id") or 0)

        path = AccountingController._validate_finance_path(
            db,
            tenant_id=tenant_id,
            domain_name="Expenses",
            category_taxonomy_id=category_id,
            subcategory_taxonomy_id=subcategory_id,
        )

        atomic_unit = AccountingController._validate_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=payload.get("atomic_unit_id"),
        )

        item_name = (
            atomic_unit.name
            if atomic_unit
            else str(payload.get("item_name") or "").strip()
        )

        if not item_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specific item is required",
            )

        category = path["category"]
        subcategory = path["subcategory"]

        log = FinancialEventEmitter.expense_posted(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            client_reference=client_reference,
            amount=amount,
            currency=payload.get("currency") or "XAF",
            channel=channel,
            taxonomy_node_id=subcategory.id,
            occurred_at=_parse_dt(payload.get("occurred_at")),
            meta={
                "domain_taxonomy_id": path["domain"].id,
                "domain_name": path["domain"].name,
                "category_taxonomy_id": category.id,
                "category_name": category.name,
                "subcategory_taxonomy_id": subcategory.id,
                "subcategory_name": subcategory.name,
                "item_mode": payload.get("item_mode") or "free_text",
                "atomic_unit_id": atomic_unit.id if atomic_unit else None,
                "item_name": item_name,
                "vendor": payload.get("vendor"),
                "receipt_ref": payload.get("receipt_ref"),
                "reference": payload.get("reference"),
                "note": payload.get("note"),
                "created_by_user_id": user_id,
            },
        )

        try:
            db.flush()
            db.commit()

            if log:
                db.refresh(log)

            return {
                "ok": True,
                "event": _serialize_log(log),
            }

        except Exception:
            db.rollback()
            raise

    # ========================================================
    # CASH MOVEMENT CREATE
    # ========================================================

    @staticmethod
    def create_cash_movement(
        *,
        request: Request,
        db: Session,
        payload: Dict[str, Any],
    ):
        ctx = _ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx.get("user_id")

        amount = _d(payload.get("amount"))

        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero",
            )

        client_reference = str(payload.get("client_reference") or "").strip()
        if not client_reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_reference is required",
            )

        source_channel = _safe_channel(payload.get("source_channel"))
        target_channel = _safe_channel(payload.get("target_channel"))

        if source_channel == target_channel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and target channels cannot be the same",
            )

        log = FinancialEventEmitter.cash_move_manual(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            client_reference=client_reference,
            amount=amount,
            currency=payload.get("currency") or "XAF",
            source_channel=source_channel,
            target_channel=target_channel,
            occurred_at=_parse_dt(payload.get("occurred_at")),
            meta={
                "reason": payload.get("reason"),
                "reference": payload.get("reference"),
                "created_by_user_id": user_id,
            },
        )

        try:
            db.flush()
            db.commit()

            if log:
                db.refresh(log)

            return {
                "ok": True,
                "event": _serialize_log(log),
            }

        except Exception:
            db.rollback()
            raise