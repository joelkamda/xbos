# core/api/kernel_router.py

from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import get_db

# Subsystems
from core.auth.auth_controller import auth_router
from core.api.tenant_controller import router as tenant_router
from core.api.orders.orders_router import router as orders_router
from core.api.sales.sales_router import router as sales_router
from core.api.taxonomy.taxonomy_router import router as taxonomy_router
from core.api.catalog.catalog_router import router as catalog_router
from core.api.accounting.accounting_router import router as accounting_router
from core.api.reports.reports_router import router as reports_router
from core.api.inventory.inventory_router import router as inventory_router

# Users / Roles
from core.users.user_controller import router as users_router
from core.rbac.roles.role_controller import router as roles_router

# Payments & Receipts
from core.api.payments.payments_router import router as payments_router
from core.api.payments.receipts_router import router as receipts_router

# XAFPay Webhook Router
from core.api.xafpay_webhook import router as xafpay_webhook_router
from core.integrations.xafpay_v2.router import router as xafpay_v2_router


# ====================================================
# MASTER KERNEL ROUTER
# ====================================================
kernel_router = APIRouter(prefix="/kernel", tags=["Kernel"])


# ----------------------------------------------------
# Kernel Internal Health Endpoints
# ----------------------------------------------------
@kernel_router.get("/health", tags=["Kernel"])
def kernel_health():
    return {"status": "ok", "service": "kernel"}


@kernel_router.get("/db-check", tags=["Kernel"])
def kernel_db_check(db=Depends(get_db)):
    """Perform a lightweight probe through the application's DB authority."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"database": "unavailable"},
        )
    return {"database": "connected"}


@kernel_router.get("/whoami", tags=["Kernel"])
def whoami(request: Request):
    return request.state.user


# ====================================================
# ADMIN-ONLY TEST ENDPOINT (RBAC PROBE)
# ====================================================
def require_admin(request: Request):
    user = request.state.user

    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="FORBIDDEN")

    return user


@kernel_router.get("/admin/health", tags=["Admin"])
def admin_health(
    request: Request,
    user=Depends(require_admin),
):
    return {
        "status": "ok",
        "scope": "admin",
        "user_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "branch_id": user["branch_id"],
    }


# ====================================================
# SUBSYSTEM ROUTERS
# ====================================================

# Auth → /kernel/auth/*
kernel_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["Auth"],
)

# Tenant → /kernel/tenant/*
kernel_router.include_router(
    tenant_router,
    prefix="/tenant",
    tags=["Tenants"],
)

# Users → /kernel/users/*
kernel_router.include_router(
    users_router,
    prefix="/users",
    tags=["Users"],
)

# Roles → /kernel/roles/*
kernel_router.include_router(
    roles_router,
    prefix="/roles",
    tags=["Roles"],
)

# Sales → /kernel/sales/*
kernel_router.include_router(
    sales_router,
    prefix="/sales",
    tags=["Sales"],
)

# Payments → /kernel/payments/*
kernel_router.include_router(
    payments_router,
    prefix="/payments",
    tags=["Payments"],
)

# Receipts → /kernel/payments/receipts/*
kernel_router.include_router(
    receipts_router,
    prefix="/payments",
    tags=["Receipts"],
)

# XAFPay Webhook → /kernel/payments/xafpay/webhook
# Route inside webhook file MUST be: @router.post("/xafpay/webhook")
kernel_router.include_router(
    xafpay_webhook_router,
    prefix="/payments",
    tags=["XafPay"],
)

# XafPay Gateway V2 signed internal-consumer endpoint.
# Authentication is the Gateway event signature; XBOS tenant/location is resolved from the bound attempt.
kernel_router.include_router(
    xafpay_v2_router,
    prefix="/integrations/xafpay-v2",
    tags=["XafPay V2"],
)

# Taxonomy → /kernel/taxonomy/*
kernel_router.include_router(
    taxonomy_router,
    prefix="/taxonomy",
    tags=["Taxonomy"],
)

# Catalog → /kernel/catalog/*
kernel_router.include_router(
    catalog_router,
    prefix="/catalog",
    tags=["Catalog"],
)

# Accounting → /kernel/accounting/*
kernel_router.include_router(
    accounting_router,
    prefix="/accounting",
    tags=["Accounting"],
)

# Reports → /kernel/reports/*
kernel_router.include_router(
    reports_router,
    prefix="/reports",
    tags=["Reports"],
)

# Inventory → /kernel/inventory/*
kernel_router.include_router(
    inventory_router,
    prefix="/inventory",
    tags=["Inventory"],
)

# Orders → /kernel/orders/*
kernel_router.include_router(
    orders_router,
    prefix="/orders",
    tags=["Orders"],
)
