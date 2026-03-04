import uuid
from decimal import Decimal
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from settings import settings

from core.domain.payments.service import PaymentService
from core.domain.payments.repository import PaymentIntentRepository
from core.domain.sales.repository import SaleRepository


class PaymentsController:

    # =====================================================
    # POS SETTLEMENT (🔥 THIS WAS MISSING)
    # =====================================================

    async def pos_settle(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        """
        Apply POS settlement (cash / mtn / orange / split / unpaid).

        This updates:
        - payment_attempts
        - payment_intents.total_paid
        - payment_intents.balance_due
        - sale.status
        """

        ctx = getattr(request.state, "user", None)
        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        sale_id = payload.get("sale_id")
        client_reference = payload.get("client_reference")
        lines: List[Dict[str, Any]] = payload.get("lines") or []
        note = payload.get("note")

        if not sale_id:
            raise HTTPException(status_code=400, detail="sale_id is required")

        if not client_reference:
            raise HTTPException(status_code=400, detail="client_reference is required")

        if not isinstance(lines, list) or len(lines) == 0:
            raise HTTPException(status_code=400, detail="lines[] required")

        # -------------------------------------------------
        # Validate Sale
        # -------------------------------------------------
        sale = SaleRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            sale_id=sale_id,
        )

        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")

        # -------------------------------------------------
        # Ensure intent exists
        # -------------------------------------------------
        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale.id,
        )

        if not intent:
            raise HTTPException(
                status_code=500,
                detail="PaymentIntent missing for sale",
            )

        # -------------------------------------------------
        # Apply settlement (CORE ENGINE)
        # -------------------------------------------------
        intent = PaymentService.apply_pos_settlement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            sale_id=sale.id,
            created_by_user_id=user_id,
            client_reference=str(client_reference),
            lines=lines,
            note=note,
        )

        db.commit()
        db.refresh(intent)

        return {
            "status": "ok",
            "sale_id": sale.id,
            "intent_id": intent.id,
            "total_paid": float(intent.total_paid or 0),
            "balance_due": float(intent.balance_due or 0),
            "intent_status": intent.status.value
            if hasattr(intent.status, "value")
            else str(intent.status),
        }

    # =====================================================
    # XAFPAY INIT (authoritative intent flow)
    # =====================================================

    async def init_xafpay_payment(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):

        ctx = getattr(request.state, "user", None)
        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        sale_id = payload.get("sale_id")
        rail = payload.get("provider")
        client_reference = payload.get("client_reference") or str(uuid.uuid4())

        if not sale_id or not rail:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sale_id and provider are required",
            )

        # -------------------------------------------------
        # Validate Sale
        # -------------------------------------------------
        sale = SaleRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            sale_id=sale_id,
        )

        if not sale:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sale not found",
            )

        # -------------------------------------------------
        # Normalize rail
        # -------------------------------------------------
        rail_normalized = str(rail).strip().lower()
        if not rail_normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment rail",
            )

        # -------------------------------------------------
        # Ensure ONE intent per sale
        # -------------------------------------------------
        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale.id,
        )

        if not intent:
            intent = PaymentService.init_intent(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                payable_type="sale",
                payable_id=sale.id,
                currency="XAF",
                amount=Decimal(str(sale.total)),  # NET ONLY
                channel="xafpay",
                created_by_user_id=user_id,
                client_reference=f"sale-intent:{tenant_id}:{branch_id}:{sale.id}",
                meta={
                    "sale_id": sale.id,
                    "source": "PaymentsController.init_xafpay_payment",
                },
            )
            db.flush()

        # -------------------------------------------------
        # Redirect URLs
        # -------------------------------------------------
        web_base = getattr(
            settings,
            "WEB_BASE_URL",
            "http://localhost:5173",
        ).rstrip("/")

        return_url = str(
            payload.get("returnUrl")
            or f"{web_base}/result?status=success&saleId={sale.id}&intentId={intent.id}"
        )

        cancel_url = str(
            payload.get("cancelUrl")
            or f"{web_base}/result?status=failure&saleId={sale.id}"
        )

        # -------------------------------------------------
        # Call Gateway
        # -------------------------------------------------
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{settings.GATEWAY_BASE_URL}/api/v1/payment-intents",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": settings.GATEWAY_API_KEY,
                        "Idempotency-Key": str(uuid.uuid4()),
                    },
                    json={
                        "amount": float(intent.amount),  # NET
                        "currency": intent.currency,
                        "provider": "tranzak",
                        "requestedRail": rail_normalized,
                        "description": f"{rail_normalized} payment for Sale #{sale.id}",
                        "customer": {
                            "email": "pos@xbos.local",
                            "phone": "670000000",
                        },
                        "externalId": str(intent.id),
                        "returnUrl": return_url,
                        "cancelUrl": cancel_url,
                    },
                )

            if response.status_code not in (200, 201):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=response.text,
                )

            gateway_data = response.json()

        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to XafPay Gateway",
            )

        gateway_intent_id = gateway_data.get("id")
        payment_url = gateway_data.get("paymentUrl")

        if not gateway_intent_id or not payment_url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid Gateway response",
            )

        PaymentIntentRepository.set_gateway_id(
            intent=intent,
            gateway_intent_id=gateway_intent_id,
        )

        db.commit()
        db.refresh(intent)

        return {
            "intent_id": intent.id,
            "sale_id": sale.id,
            "gateway_intent_id": gateway_intent_id,
            "paymentUrl": payment_url,
            "status": intent.status.value,
        }