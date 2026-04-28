from sqlalchemy.orm import Session

from core.domain.orders.repository import OrderRepository
from core.domain.sales.service import SaleService
from core.domain.sales.repository import SaleRepository
from core.domain.payments.service import PaymentService


class CommerceService:

    @staticmethod
    def settle_order(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int,
        created_by_user_id: int,
        client_reference: str,
        lines,
    ):

        # -------------------------
        # 1. Resolve or create sale
        # -------------------------
        sale = SaleRepository.get_by_order_id(
            db,
            tenant_id=tenant_id,
            order_id=order_id,
        )

        if not sale:

            order = OrderRepository.get_by_id(db, order_id)
            if not order:
                raise ValueError("Order not found")

            sale = SaleService.create_sale_from_order(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                cashier_id=created_by_user_id,
                order=order,
            )

        # -------------------------
        # 2. Apply payment
        # -------------------------
        intent = PaymentService.apply_pos_settlement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            sale_id=sale.id,   # 🔥 ONLY sale_id now
            created_by_user_id=created_by_user_id,
            client_reference=client_reference,
            lines=lines,
        )

        # -------------------------
        # 3. Mark order paid
        # -------------------------
        if intent.balance_due <= 0:
            OrderRepository.mark_paid(order)

        return intent