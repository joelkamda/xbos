from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from core.domain.sales.models import (
    Sale,
    SaleItem,
    SaleStatus,
    PaymentMethod,
)
from core.domain.sales.repository import SaleRepository
from core.domain.catalog.repository import BillableUnitRepository
from core.domain.sales.receipt import generate_receipt_no

from core.domain.payments.service import PaymentService

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


class SaleService:
    """
    Core POS engine — Tier-1 authority (NEW SYSTEM).

    Invariants:
    - Sale ALWAYS has exactly ONE PaymentIntent (authoritative).
    - Settlement is expressed as PaymentAttempts (split-safe, async-safe).
    - NO legacy Payment table usage.

    Totals:
    - sale.subtotal = GROSS (sum of line totals)
    - sale.total    = NET (gross - discount - complimentary)
    """

    @staticmethod
    def list_sales(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 50,
    ) -> List[Sale]:
        return SaleRepository.list_for_branch(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            limit=limit,
        )

    @staticmethod
    def create_sale(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        cashier_id: int,
        payload: Dict[str, Any],
    ) -> Sale:
        # -------------------------
        # Idempotency (sale)
        # -------------------------
        client_reference = payload.get("client_reference")
        if not client_reference:
            raise ValueError("client_reference is required")

        existing = check_idempotency_key(db, key=client_reference, scope="sale")
        if existing:
            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=existing.reference_id,
            )
            if not sale:
                raise ValueError("Idempotency key points to missing sale")
            return sale

        # -------------------------
        # Validate items
        # -------------------------
        items_payload = payload.get("items")
        if not items_payload:
            raise ValueError("Sale must contain at least one item")

        # -------------------------
        # payment_method (MAKE OPTIONAL)
        # -------------------------
        payment_method_raw = payload.get("payment_method") or "cash"
        if payment_method_raw not in PaymentMethod._value2member_map_:
            raise ValueError("Invalid payment_method")
        payment_method = PaymentMethod(payment_method_raw)

        currency = (payload.get("currency") or "XAF").upper()

        # -------------------------
        # Discounts / Complimentary
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
        # Build SaleItems (gross)
        # -------------------------
        sale_items: List[SaleItem] = []
        gross_total = Decimal("0")

        for item in items_payload:
            billable_unit_id = item.get("billable_unit_id")
            quantity = int(item.get("quantity", 0))

            if quantity <= 0:
                raise ValueError("Quantity must be positive")

            billable_unit = BillableUnitRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                billable_unit_id=billable_unit_id,
            )

            if not billable_unit or not billable_unit.is_active:
                raise ValueError(f"Invalid or inactive billable unit: {billable_unit_id}")

            unit_price = _d(billable_unit.price)
            line_total = unit_price * Decimal(quantity)

            sale_items.append(
                SaleItem(
                    billable_unit_id=billable_unit.id,
                    name_snapshot=billable_unit.name,
                    unit_price=unit_price,
                    quantity=quantity,
                    line_total=line_total,
                )
            )
            gross_total += line_total

        # -------------------------
        # NET total (client pays)
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

        # New system: start pending; settlement will flip to paid
        sale = Sale(
            tenant_id=tenant_id,
            branch_id=branch_id,
            cashier_id=cashier_id,
            receipt_no=receipt_no,
            status=SaleStatus.pending_payment,
            payment_method=payment_method.value,
            subtotal=gross_total,
            total=net_total,
            created_at=now,
        )

        try:
            SaleRepository.create(db, sale=sale)
            db.flush()

            for si in sale_items:
                si.sale = sale
            SaleRepository.create_items(db, items=sale_items)

            # Always create ONE intent per sale (amount = NET)
            intent_client_ref = f"sale-intent:{tenant_id}:{branch_id}:{sale.id}"

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
                client_reference=intent_client_ref,
                meta={
                    "receipt_no": sale.receipt_no,
                    "source": "SaleService.create_sale",

                    # receipt-critical
                    "gross_total": float(gross_total),
                    "discount_total": float(discount_total),
                    "discount_reason": str(discount_reason) if discount_reason else None,
                    "complimentary_total": float(complimentary_total),
                    "complimentary_items": complimentary_items,
                    "net_total": float(net_total),

                    "initial_payment_method": payment_method.value,
                },
            )

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
            raise