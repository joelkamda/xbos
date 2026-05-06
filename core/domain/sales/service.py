from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from core.domain.sales.models import (
    Sale,
    SaleItem,
    SaleStatus,
    PaymentMethod,
)
from core.domain.sales.repository import SaleRepository
from core.domain.catalog.repository import AtomicUnitRepository
from core.domain.sales.receipt import generate_receipt_no
from core.domain.payments.service import PaymentService
from core.domain.accounting.emitter import FinancialEventEmitter
from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)


def _d(v: Any) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


class SaleService:
    """
    Core POS engine — Tier-1 authority.

    Invariants:
    - Sale ALWAYS has exactly ONE PaymentIntent
    - Settlement handled via PaymentAttempts
    - Sale is immutable after creation (except status)

    Totals:
    - subtotal = GROSS
    - total    = NET

    Accounting:
    - Sale creation emits non-cashflow revenue events:
        SALE_REVENUE_GROSS
        DISCOUNT_APPLIED
        COMPLIMENTARY_APPLIED
    - Payment collection remains handled by PaymentService / PaymentAttempts.
    """

    # =====================================================
    # ORDER → SALE
    # =====================================================

    @staticmethod
    def create_sale_from_order(db, *, tenant_id, branch_id, cashier_id, order):

        if not order:
            raise ValueError("order is required")

        # HARD GUARD: prevent duplicate sale for same order
        existing_sale = SaleRepository.get_by_order_id(
            db,
            tenant_id=tenant_id,
            order_id=order.id,
        )
        if existing_sale:
            return existing_sale

        payload = {
            "client_reference": f"order:{order.id}",
            "order_id": order.id,
            "items": [
                {
                    "atomic_unit_id": i.atomic_unit_id,
                    "quantity": i.quantity,
                }
                for i in order.items
            ],
        }

        sale = SaleService.create_sale(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            cashier_id=cashier_id,
            payload=payload,
        )

        return sale

    # =====================================================
    # LIST
    # =====================================================

    @staticmethod
    def list_sales(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> List[Sale]:

        query = (
            db.query(Sale)
            .options(selectinload(Sale.items))
            .filter(
                Sale.tenant_id == tenant_id,
                Sale.branch_id == branch_id,
            )
            .order_by(Sale.created_at.desc())
        )

        if status:
            query = query.filter(Sale.status == status)

        return query.limit(limit).all()

    # =====================================================
    # ACCOUNTING EMISSION
    # =====================================================

    @staticmethod
    def _emit_sale_accounting_events(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        cashier_id: int,
        sale: Sale,
        gross_total: Decimal,
        discount_total: Decimal,
        discount_reason: Any,
        complimentary_total: Decimal,
        complimentary_items: Any,
        net_total: Decimal,
        currency: str,
    ) -> None:
        """
        Emit non-cashflow accounting events for the commercial sale.

        Important:
        - These events recognize the sale economics.
        - Actual collection is emitted later by PaymentService as PAYMENT_RECEIVED.
        - Emitter is idempotent, so retrying sale creation does not duplicate ledger rows.
        """

        base_meta = {
            "sale_id": sale.id,
            "receipt_no": sale.receipt_no,
            "cashier_id": cashier_id,
            "gross_total": float(gross_total),
            "discount_total": float(discount_total),
            "complimentary_total": float(complimentary_total),
            "net_total": float(net_total),
            "source": "sale_creation",
        }

        FinancialEventEmitter.sale_revenue_gross(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            sale_id=sale.id,
            amount=gross_total,
            currency=currency,
            meta={
                **base_meta,
                "event_reason": "gross_sale_created",
            },
        )

        if discount_total > 0:
            FinancialEventEmitter.sale_discount(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale.id,
                amount=discount_total,
                currency=currency,
                meta={
                    **base_meta,
                    "event_reason": "discount_applied",
                    "discount_reason": discount_reason,
                },
            )

        if complimentary_total > 0:
            FinancialEventEmitter.sale_complimentary(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale.id,
                amount=complimentary_total,
                currency=currency,
                meta={
                    **base_meta,
                    "event_reason": "complimentary_applied",
                    "complimentary_items": complimentary_items,
                },
            )

    # =====================================================
    # CREATE SALE
    # =====================================================

    @staticmethod
    def create_sale(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        cashier_id: int,
        payload: Dict[str, Any],
    ) -> Sale:

        client_reference = payload.get("client_reference")
        if not client_reference:
            raise ValueError("client_reference is required")

        # -------------------------
        # Idempotency
        # -------------------------
        existing = check_idempotency_key(db, key=client_reference, scope="sale")
        if existing:
            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=existing.reference_id,
            )
            if not sale:
                raise ValueError("Broken idempotency reference")
            return sale

        # -------------------------
        # Validate items
        # -------------------------
        items_payload = payload.get("items")
        if not items_payload:
            raise ValueError("Sale must contain at least one item")

        # -------------------------
        # Order linkage
        # -------------------------
        order_id = payload.get("order_id")

        if order_id:
            existing_sale = SaleRepository.get_by_order_id(
                db,
                tenant_id=tenant_id,
                order_id=order_id,
            )
            if existing_sale:
                return existing_sale

        # -------------------------
        # Payment method
        # -------------------------
        payment_method_raw = payload.get("payment_method") or "cash"
        if payment_method_raw not in PaymentMethod._value2member_map_:
            raise ValueError("Invalid payment_method")

        payment_method = PaymentMethod(payment_method_raw)
        currency = (payload.get("currency") or "XAF").upper()

        # -------------------------
        # Discounts / complimentary
        # -------------------------
        discount_total = _d(payload.get("discount_total") or 0)
        discount_reason = payload.get("discount_reason")

        complimentary_total = _d(payload.get("complimentary_total") or 0)
        complimentary_items = payload.get("complimentary_items") or []

        if discount_total < 0:
            discount_total = Decimal("0")

        if complimentary_total < 0:
            complimentary_total = Decimal("0")

        # -------------------------
        # Build items
        # -------------------------
        sale_items: List[SaleItem] = []
        gross_total = Decimal("0")

        for item in items_payload:
            atomic_unit_id = item.get("atomic_unit_id")
            quantity = int(item.get("quantity", 0))

            if not atomic_unit_id:
                raise ValueError("atomic_unit_id required")

            if quantity <= 0:
                raise ValueError("Quantity must be positive")

            atomic_unit = AtomicUnitRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not atomic_unit or not atomic_unit.is_active:
                raise ValueError(f"Invalid atomic unit: {atomic_unit_id}")

            unit_price = _d(atomic_unit.unit_price)
            line_total = unit_price * Decimal(quantity)

            sale_items.append(
                SaleItem(
                    atomic_unit_id=atomic_unit.id,
                    name_snapshot=atomic_unit.name,
                    unit_price=unit_price,
                    quantity=quantity,
                    line_total=line_total,
                )
            )

            gross_total += line_total

        # -------------------------
        # Net total
        # -------------------------
        net_total = gross_total - discount_total - complimentary_total
        if net_total < 0:
            net_total = Decimal("0")

        now = datetime.utcnow()

        receipt_no = generate_receipt_no(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            created_at=now,
        )

        # -------------------------
        # Create Sale
        # -------------------------
        sale = Sale(
            tenant_id=tenant_id,
            branch_id=branch_id,
            cashier_id=cashier_id,
            receipt_no=receipt_no,
            status=SaleStatus.pending_payment,
            payment_method=payment_method.value,
            subtotal=gross_total,
            total=net_total,
            discount_total=discount_total,
            complimentary_total=complimentary_total,
            created_at=now,
            order_id=order_id,
        )

        try:
            SaleRepository.create(db, sale=sale)
            db.flush()

            for si in sale_items:
                si.sale = sale

            SaleRepository.create_items(db, items=sale_items)

            # -------------------------
            # PaymentIntent
            # -------------------------
            intent_ref = f"intent:sale:{tenant_id}:{branch_id}:{sale.id}"

            PaymentService.init_intent(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                payable_type="sale",
                payable_id=sale.id,
                currency=currency,
                amount=net_total,
                channel="pos",
                created_by_user_id=cashier_id,
                client_reference=intent_ref,
                meta={
                    "receipt_no": sale.receipt_no,
                    "gross_total": float(gross_total),
                    "discount_total": float(discount_total),
                    "discount_reason": discount_reason,
                    "complimentary_total": float(complimentary_total),
                    "complimentary_items": complimentary_items,
                    "net_total": float(net_total),
                    "source": "sale_creation",
                },
            )

            # -------------------------
            # Accounting events
            # -------------------------
            SaleService._emit_sale_accounting_events(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                cashier_id=cashier_id,
                sale=sale,
                gross_total=gross_total,
                discount_total=discount_total,
                discount_reason=discount_reason,
                complimentary_total=complimentary_total,
                complimentary_items=complimentary_items,
                net_total=net_total,
                currency=currency,
            )

            # -------------------------
            # Idempotency record
            # -------------------------
            record_idempotency_key(
                db,
                key=client_reference,
                scope="sale",
                reference_id=sale.id,
            )

            db.commit()
            db.refresh(sale)

            return sale

        except IntegrityError:
            db.rollback()

            # Race-safe recovery for order-driven sale creation
            if order_id:
                existing_sale = SaleRepository.get_by_order_id(
                    db,
                    tenant_id=tenant_id,
                    order_id=order_id,
                )
                if existing_sale:
                    return existing_sale

            raise