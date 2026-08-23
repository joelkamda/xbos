"""HTTP client for the frozen internal XafPay Gateway V2 XBOS contract."""

from __future__ import annotations

from typing import Any

import httpx

from .contract import (
    XafPayV2CreatePaymentRequest,
    XafPayV2CreatePaymentResponse,
    XafPayV2CreateRefundRequest,
    XafPayV2CreateRefundResponse,
    XafPayV2IntegrationError,
)


class XafPayV2Client:
    def __init__(self, base_url: str, service_credential: str, *, timeout_seconds: float = 10.0):
        self.base_url = str(base_url).strip().rstrip("/")
        self.service_credential = str(service_credential).strip()
        self.timeout_seconds = timeout_seconds
        if not self.base_url.startswith(("http://127.0.0.1", "http://localhost", "https://")):
            raise XafPayV2IntegrationError("gateway_url_invalid", "Gateway URL must be local proof HTTP or HTTPS")
        if not self.service_credential.startswith("xps_") or "." not in self.service_credential:
            raise XafPayV2IntegrationError("gateway_credential_invalid", "Gateway service credential is invalid")

    def _post(self, path: str, idempotency_key: str, body: dict[str, Any], error_code: str) -> Any:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.service_credential}",
                    "Idempotency-Key": idempotency_key,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise XafPayV2IntegrationError("gateway_transport_error", str(exc)) from exc
        if response.status_code < 200 or response.status_code > 299:
            detail = response.text[:500]
            raise XafPayV2IntegrationError(error_code, f"HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise XafPayV2IntegrationError("gateway_response_invalid", "Gateway response is not JSON") from exc

    def create_payment(self, request: XafPayV2CreatePaymentRequest) -> XafPayV2CreatePaymentResponse:
        payload = self._post("/v2/payments", request.idempotency_key, request.body(), "gateway_create_rejected")
        return XafPayV2CreatePaymentResponse.parse(payload, request)

    def create_refund(self, request: XafPayV2CreateRefundRequest) -> XafPayV2CreateRefundResponse:
        payload = self._post("/v2/refunds", request.idempotency_key, request.body(), "gateway_refund_rejected")
        return XafPayV2CreateRefundResponse.parse(payload, request)
