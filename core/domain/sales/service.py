from typing import Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from core.domain.sales.models import (
    Sale,
    SaleItem,
    SaleStatus,
    PaymentMethod,
)
from core.domain.payments.models import (
    Payment,
    PaymentStatus,
)
from core.domain.sales.repository import SaleRepository
from core.domain.payments.repository import PaymentRepository
from core.domain.catalog.repository import BillableUnitRepository
from core.domain.sales.receipt import generate_receipt_no

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)


class SaleService:
    """
    Core POS engine — Tier-1 authority.
    """

    # -------------------------------------------------
    # READ
    # -------------------------------------------------

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

    # -------------------------------------------------
    # WRITE
    # -------------------------------------------------

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
        # Idempotency
        # -------------------------
        client_reference = payload.get("client_reference")
        if not client_reference:
            raise ValueError("client_reference is required")

        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="sale",
        )
        if existing:
            return SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=existing.reference_id,
            )

        # -------------------------
        # Validate intent
        # -------------------------
        items_payload = payload.get("items")
        if not items_payload:
            raise ValueError("Sale must contain at least one item")

        payment_method_raw = payload.get("payment_method")
        if payment_method_raw not in PaymentMethod._value2member_map_:
            raise ValueError("Invalid payment_method")

        payment_method = PaymentMethod(payment_method_raw)

        # -------------------------
        # Build SaleItems
        # -------------------------
        sale_items: List[SaleItem] = []
        subtotal = 0

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
                raise ValueError(
                    f"Invalid or inactive billable unit: {billable_unit_id}"
                )

            unit_price = billable_unit.price
            line_total = unit_price * quantity

            sale_items.append(
                SaleItem(
                    billable_unit_id=billable_unit.id,
                    name_snapshot=billable_unit.name,
                    unit_price=unit_price,
                    quantity=quantity,
                    line_total=line_total,
                )
            )

            subtotal += line_total

        total = subtotal

        # -------------------------
        # Create Sale
        # -------------------------
        now = datetime.utcnow()

        receipt_no = generate_receipt_no(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            created_at=now,
        )

        sale = Sale(
            tenant_id=tenant_id,
            branch_id=branch_id,
            cashier_id=cashier_id,
            receipt_no=receipt_no,
            status=(
                SaleStatus.paid
                if payment_method == PaymentMethod.cash
                else SaleStatus.pending_payment
            ),
            payment_method=payment_method.value,
            subtotal=subtotal,
            total=total,
            created_at=now,
        )

        try:
            # 1️⃣ Persist Sale
            SaleRepository.create(db, sale=sale)

            # 🔥 CRITICAL: ensure sale.id exists
            db.flush()

            # 2️⃣ Persist items
            for item in sale_items:
                item.sale = sale

            SaleRepository.create_items(db, items=sale_items)

            # 3️⃣ CASH → immediate payment
            if payment_method == PaymentMethod.cash:
                PaymentRepository.create(
                    db,
                    payment=Payment(
                        sale_id=sale.id,
                        method=PaymentMethod.cash,
                        provider=None,
                        amount=total,
                        status=PaymentStatus.paid,
                        completed_at=now,
                    ),
                )

            # 4️⃣ Idempotency
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
