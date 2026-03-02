import uuid
from decimal import Decimal
from typing import Any, Dict

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from settings import settings

from core.domain.payments.service import PaymentService
from core.domain.payments.repository import PaymentIntentRepository
from core.domain.sales.repository import SaleRepository


class PaymentsController:

    # -------------------------------------------------
    # XAFPAY INIT (PaymentIntent-based architecture)
    # -------------------------------------------------

    async def init_xafpay_payment(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        ctx = getattr(request.state, "user", None)
        if not ctx:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        sale_id = payload.get("sale_id")
        rail = payload.get("provider")  # mtn, orange, wallet
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
        # Normalize rail (XBOS does NOT validate adapters)
        # -------------------------------------------------
        rail_normalized = str(rail).strip().lower()

        if not rail_normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment rail",
            )

        print("🔥 SENDING RAIL TO GATEWAY:", rail_normalized)

        # -------------------------------------------------
        # 1️⃣ Create PaymentIntent (idempotent)
        # -------------------------------------------------
        intent = PaymentService.init_intent(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            payable_type="sale",
            payable_id=sale.id,
            currency="XAF",
            amount=Decimal(str(sale.total)),
            channel="xafpay",
            created_by_user_id=user_id,
            client_reference=client_reference,
            meta={
                "rail": rail_normalized,
                "sale_id": sale.id,
            },
        )

        db.flush()

        print("🔥 CALLING GATEWAY FOR PAYMENT INTENT")

        # -------------------------------------------------
        # 2️⃣ Redirect URLs
        # -------------------------------------------------
        web_base = getattr(
            settings,
            "WEB_BASE_URL",
            "http://localhost:5173"
        ).rstrip("/")

        return_url = str(
            payload.get("returnUrl")
            or f"{web_base}/result?status=success"
        )

        cancel_url = str(
            payload.get("cancelUrl")
            or f"{web_base}/result?status=failure"
        )

        idem_key = str(uuid.uuid4())

        # -------------------------------------------------
        # 3️⃣ Call Gateway
        # -------------------------------------------------
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{settings.GATEWAY_BASE_URL}/api/v1/payment-intents",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": settings.GATEWAY_API_KEY,
                        "Idempotency-Key": idem_key,
                    },
                    json={
                        "amount": float(intent.amount),
                        "currency": intent.currency,
                        "provider": "tranzak",  # XBOS always uses XafPay channel
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
                print("❌ Gateway error:", response.text)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=response.text,
                )

            gateway_data = response.json()

        except httpx.RequestError as e:
            print("❌ Gateway connection error:", str(e))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to XafPay Gateway",
            )

        # -------------------------------------------------
        # 4️⃣ Extract response
        # -------------------------------------------------
        gateway_intent_id = gateway_data.get("id")
        payment_url = gateway_data.get("paymentUrl")

        if not gateway_intent_id or not payment_url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid Gateway response",
            )

        # -------------------------------------------------
        # 5️⃣ Save gateway reference on Intent
        # -------------------------------------------------
        PaymentIntentRepository.set_gateway_id(
            intent=intent,
            gateway_intent_id=gateway_intent_id,
        )

        db.commit()
        db.refresh(intent)

        print("✅ Gateway Intent Created:", gateway_intent_id)
        print("🌐 Payment URL:", payment_url)

        # -------------------------------------------------
        # 6️⃣ Return to frontend
        # -------------------------------------------------
        return {
            "intent_id": intent.id,
            "sale_id": sale.id,
            "gateway_intent_id": gateway_intent_id,
            "paymentUrl": payment_url,
            "status": intent.status,
        }