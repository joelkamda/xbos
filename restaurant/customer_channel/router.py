from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db

from .auth import bearer_from_authorization_header, catalog_bearer_from_authorization_header
from .contracts import CatalogReadError, H1BError, PRIVATE_ROUTE_PREFIX
from .service import RestaurantCustomerChannelCheckoutAuthority
from .catalog_read import CatalogReadTransport

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

def _catalog_failure(error: CatalogReadError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.envelope())

def _catalog_common(request: Request) -> tuple[str, str, str | None, str | None]:
    trace = request.headers.get("X-Correlation-Ref")
    if trace is None or not trace.strip():
        raise CatalogReadError("CATALOG_REQUEST_INVALID")
    trace = trace.strip()
    token = catalog_bearer_from_authorization_header(
        request.headers.get("Authorization"), correlation_ref=trace
    )
    return (
        trace,
        token,
        request.headers.get("X-Service-Principal"),
        request.headers.get("X-Service-Scopes"),
    )
def _catalog_uuid(value: Any, trace: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:
        raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace) from exc

def _catalog_at(value: Any, trace: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace)
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except Exception as exc:
        raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace)
    return parsed

def _catalog_transport_call(request: Request):
    trace, token, principal, scopes = _catalog_common(request)
    return trace, token, principal, scopes
@router.post("/context-attestations")
async def attest_catalog_context(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        if set(payload) != {"context_binding_ref", "effective_at"}:
            raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace)
        trace, token, principal, scopes = _catalog_transport_call(request)
        result = CatalogReadTransport(db).attest_context(
            context_binding_ref=_catalog_uuid(payload["context_binding_ref"], trace),
            effective_at=_catalog_at(payload["effective_at"], trace),
            raw_token=token,
            principal=principal,
            scopes=scopes,
            correlation_ref=trace,
        )
        return result
    except CatalogReadError as exc:
        return _catalog_failure(exc)
    except Exception:
        return _catalog_failure(CatalogReadError("CATALOG_SEMANTIC_FAILURE", correlation_ref=trace))
@router.post("/catalog-bindings/resolve")
async def resolve_catalog_binding(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        expected = {"context_binding_ref", "merchant_public_id", "location_public_id", "effective_at"}
        if set(payload) != expected:
            raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace)
        trace, token, principal, scopes = _catalog_transport_call(request)
        return CatalogReadTransport(db).resolve_binding(
            context_binding_ref=_catalog_uuid(payload["context_binding_ref"], trace),
            merchant_public_id=_catalog_uuid(payload["merchant_public_id"], trace),
            location_public_id=_catalog_uuid(payload["location_public_id"], trace),
            effective_at=_catalog_at(payload["effective_at"], trace),
            raw_token=token,
            principal=principal,
            scopes=scopes,
            correlation_ref=trace,
        )
    except CatalogReadError as exc:
        return _catalog_failure(exc)
    except Exception:
        return _catalog_failure(CatalogReadError("CATALOG_SEMANTIC_FAILURE", correlation_ref=trace))
@router.post("/catalog/menu")
async def read_catalog_menu(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    trace = request.headers.get("X-Correlation-Ref")
    try:
        expected = {
            "context_binding_ref", "merchant_public_id", "location_public_id",
            "binding_ref", "binding_version", "effective_at",
        }
        if set(payload) != expected:
            raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace)
        trace, token, principal, scopes = _catalog_transport_call(request)
        try:
            binding_version = int(payload["binding_version"])
        except Exception as exc:
            raise CatalogReadError("CATALOG_REQUEST_INVALID", correlation_ref=trace) from exc
        return CatalogReadTransport(db).menu(
            context_binding_ref=_catalog_uuid(payload["context_binding_ref"], trace),
            merchant_public_id=_catalog_uuid(payload["merchant_public_id"], trace),
            location_public_id=_catalog_uuid(payload["location_public_id"], trace),
            binding_ref=_catalog_uuid(payload["binding_ref"], trace),
            binding_version=binding_version,
            effective_at=_catalog_at(payload["effective_at"], trace),
            raw_token=token,
            principal=principal,
            scopes=scopes,
            correlation_ref=trace,
        )
    except CatalogReadError as exc:
        return _catalog_failure(exc)
    except Exception:
        return _catalog_failure(CatalogReadError("CATALOG_SEMANTIC_FAILURE", correlation_ref=trace))
