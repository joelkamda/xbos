"""Pure protocol translation and cryptographic verification for XafPay."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol
from uuid import UUID

from .contract import (
    NormalizedXafPayCallback,
    XafPayInitiationRequest,
    XafPayInitiationResponse,
    XafPayIntegrationError,
    XafPayPaymentCreateRequest,
    XafPayPaymentCreateResponse,
)


class XafPayTransport(Protocol):
    """Injected side-effect boundary; production HTTP belongs outside the kernel."""

    def post(self, *, path: str, headers: Mapping[str, str], body: Mapping[str, Any]) -> Mapping[str, Any]: ...


class XafPayAdapter:
    PAYMENT_CREATE_PATH = "/v2/payments"
    INITIATION_PATH = "/v1/payment-intents"
    RAILS = {"mtn_momo": "mtn", "orange_money": "orange"}
    EVENT_HEADER = "x-xafpay-event-id"
    SIGNATURE_HEADER = "x-xafpay-signature"

    @classmethod
    def payment_create_envelope(
        cls,
        request: XafPayPaymentCreateRequest,
        *,
        service_credential: str,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        credential = str(service_credential).strip()
        if not credential:
            raise XafPayIntegrationError("service_credential_required", "Gateway V2 service credential is required")
        body = {
            "external_reference": request.external_reference,
            "amount": {"minor": int(request.amount), "currency": request.currency_code},
            "requested_method": request.payment_method_code.upper(),
            "requested_rail": request.payment_rail_code.upper(),
            "channel": request.channel,
        }
        headers = {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        return headers, body

    @classmethod
    def create_payment(
        cls,
        request: XafPayPaymentCreateRequest,
        *,
        service_credential: str,
        transport: XafPayTransport,
    ) -> XafPayPaymentCreateResponse:
        headers, body = cls.payment_create_envelope(request, service_credential=service_credential)
        response = transport.post(path=cls.PAYMENT_CREATE_PATH, headers=headers, body=body)
        try:
            amount = response["amount"]
            if not isinstance(amount, Mapping):
                raise TypeError
            return XafPayPaymentCreateResponse(
                payment_id=str(response["payment_id"]),
                external_reference=str(response["external_reference"]),
                status=str(response["status"]),
                amount=amount["minor"],
                currency_code=str(amount["currency"]),
                next_action=response.get("next_action"),
                evidence=dict(response),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if isinstance(exc, XafPayIntegrationError):
                raise
            raise XafPayIntegrationError("invalid_payment_create_response", "Gateway V2 payment create response is incomplete") from exc

    @classmethod
    def initiation_envelope(cls, request: XafPayInitiationRequest, *, api_key: str) -> tuple[dict[str, str], dict[str, Any]]:
        key = str(api_key).strip()
        if not key:
            raise XafPayIntegrationError("api_key_required", "XafPay API key is required")
        body = {
            "amount": int(request.amount),
            "currency": request.currency_code,
            "provider": "tranzak",
            "requestedRail": cls.RAILS[request.payment_rail_code],
            "customer": {"phone": request.customer_phone},
            "externalId": str(request.payment_attempt_public_id),
            "returnUrl": request.return_url,
            "cancelUrl": request.cancel_url,
        }
        if request.description:
            body["description"] = request.description
        return ({"Content-Type": "application/json", "X-API-Key": key, "Idempotency-Key": request.idempotency_key}, body)

    @classmethod
    def initiate(cls, request: XafPayInitiationRequest, *, api_key: str, transport: XafPayTransport) -> XafPayInitiationResponse:
        headers, body = cls.initiation_envelope(request, api_key=api_key)
        response = transport.post(path=cls.INITIATION_PATH, headers=headers, body=body)
        try:
            gateway_id = UUID(str(response["id"]))
            status = str(response["status"]).strip().lower()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise XafPayIntegrationError("invalid_initiation_response", "XafPay initiation response is incomplete") from exc
        payment_url = response.get("paymentUrl")
        return XafPayInitiationResponse(gateway_id, status, str(payment_url) if payment_url else None, dict(response))

    @staticmethod
    def payload_hash(raw_body: bytes) -> str:
        return hashlib.sha256(raw_body).hexdigest()

    @classmethod
    def verify_signature(cls, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
        normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}
        supplied = normalized.get(cls.SIGNATURE_HEADER, "").lower()
        if not raw_body or not secret or not supplied:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return len(supplied) == 64 and hmac.compare_digest(expected, supplied)

    @classmethod
    def callback_event_reference(cls, headers: Mapping[str, str]) -> str:
        normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}
        reference = normalized.get(cls.EVENT_HEADER, "")
        if not reference or len(reference) > 255:
            raise XafPayIntegrationError("callback_event_id_required", "X-Xafpay-Event-Id is required")
        return reference

    @classmethod
    def normalize_callback(cls, raw_body: bytes, headers: Mapping[str, str]) -> NormalizedXafPayCallback:
        event_reference = cls.callback_event_reference(headers)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError
            attempt_id = UUID(str(payload["payment_id"]))
            gateway_id = UUID(str(payload["gateway_intent_id"]))
            status = str(payload["status"]).strip().lower()
            amount = Decimal(str(payload["amount"]))
            currency = str(payload["currency"]).strip().upper()
            provider = str(payload["provider"]).strip().lower()
            provider_reference = str(payload.get("provider_ref") or "").strip()
            occurred_at = datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, InvalidOperation) as exc:
            raise XafPayIntegrationError("invalid_callback_payload", "XafPay callback payload is incomplete or invalid") from exc
        if status not in {"created", "pending", "processing", "requires_action", "succeeded", "paid", "confirmed", "failed", "cancelled", "expired"}:
            raise XafPayIntegrationError("unknown_callback_status", "XafPay callback status is not recognized")
        if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
            raise XafPayIntegrationError("invalid_callback_amount", "callback amount must be positive whole XAF")
        if currency != "XAF" or provider != "tranzak":
            raise XafPayIntegrationError("callback_authority_mismatch", "callback currency or provider is invalid")
        if status in {"succeeded", "paid", "confirmed"} and not provider_reference:
            raise XafPayIntegrationError("provider_reference_required", "successful callback requires provider transaction evidence")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise XafPayIntegrationError("invalid_callback_timestamp", "callback occurred_at must be timezone-aware")
        return NormalizedXafPayCallback(
            event_reference,
            cls.payload_hash(raw_body),
            attempt_id,
            gateway_id,
            status,
            amount,
            currency,
            provider,
            provider_reference,
            occurred_at,
            payload,
        )
