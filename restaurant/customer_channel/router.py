from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db

from .auth import bearer_from_authorization_header
from .contracts import H1BError, PRIVATE_ROUTE_PREFIX
from .service import RestaurantCustomerChannelCheckoutAuthority

router = APIRouter(prefix=PRIVATE_ROUTE_PREFIX, tags=["Customer Channel Private Checkout"])


def _trace(request: Request) -> str:
    value = request.headers.get("X-Correlation-Ref")
    if value is None or not value.strip():
        raise H1BError("CONTEXT_MISMATCH")
    return value.strip()


def _context_ref(request: Request, trace: str) -> UUID:
    value = request.headers.get("X-XBOS-Context-Binding-Ref")
    try:
        return UUID(str(value))
    except Exception as exc:
        raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace) from exc


def _scope(service: RestaurantCustomerChannelCheckoutAuthority, request: Request):
    trace = _trace(request)
    token = bearer_from_authorization_header(
        request.headers.get("Authorization"),
        correlation_ref=trace,
    )
    return service.trusted_scope(
        bearer_token=token,
        context_binding_ref=_context_ref(request, trace),
        correlation_ref=trace,
    )


def _failure(error: H1BError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.envelope())


def _unexpected(trace: str | None) -> JSONResponse:
    error = H1BError("ORDER_NOT_READY", correlation_ref=trace)
    return JSONResponse(status_code=error.status_code, content=error.envelope())


@router.post("/order-confirmations")
async def create_order_confirmation(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        service = RestaurantCustomerChannelCheckoutAuthority(db)
        scope = _scope(service, request)
        result = service.confirm_order(scope=scope, payload=payload)
        db.commit()
        return asdict(result)
    except H1BError as exc:
        db.rollback()
        return _failure(exc)
    except Exception:
        db.rollback()
        return _unexpected(trace)


@router.post("/orders")
async def submit_order(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        if set(payload) != {"confirmation_ref", "client_submit_ref"}:
            raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=trace)
        service = RestaurantCustomerChannelCheckoutAuthority(db)
        scope = _scope(service, request)
        result = service.submit_order(
            scope=scope,
            confirmation_ref=UUID(str(payload["confirmation_ref"])),
            client_submit_ref=str(payload["client_submit_ref"]),
        )
        db.commit()
        return asdict(result)
    except H1BError as exc:
        db.rollback()
        return _failure(exc)
    except Exception:
        db.rollback()
        return _unexpected(trace)


@router.get("/orders/by-client-submit-ref/{client_submit_ref}")
async def reconcile_order(
    client_submit_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        service = RestaurantCustomerChannelCheckoutAuthority(db)
        scope = _scope(service, request)
        result = service.reconcile_order(
            scope=scope,
            client_submit_ref=client_submit_ref,
        )
        return asdict(result)
    except H1BError as exc:
        db.rollback()
        return _failure(exc)
    except Exception:
        db.rollback()
        return _unexpected(trace)


@router.post("/orders/{order_ref}/payment-request")
async def create_payment_request(
    order_ref: UUID,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        # The accepted C3 private transport carries no caller amount, currency,
        # tenant, organization, or payment-request override.
        if payload not in (None, {}):
            forbidden = {
                "amount",
                "currency",
                "tenant_id",
                "organization_unit_id",
                "payment_request_ref",
            }
            if forbidden.intersection(payload):
                raise H1BError("PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=trace)
            if payload:
                raise H1BError("PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=trace)
        service = RestaurantCustomerChannelCheckoutAuthority(db)
        scope = _scope(service, request)
        result = service.create_payment_request(scope=scope, order_ref=order_ref)
        db.commit()
        return result
    except H1BError as exc:
        db.rollback()
        return _failure(exc)
    except Exception:
        db.rollback()
        return _unexpected(trace)
