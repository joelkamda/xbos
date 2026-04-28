from fastapi import APIRouter, Request, Depends, HTTPException

# Subsystems
from core.auth.auth_controller import auth_router
from core.api.tenant_controller import router as tenant_router
from core.api.orders.orders_router import router as orders_router
from core.api.sales.sales_router import router as sales_router
from core.api.taxonomy.taxonomy_router import router as taxonomy_router
from core.api.catalog.catalog_router import router as catalog_router
from core.api.accounting.accounting_router import router as accounting_router

# Payments & Receipts
from core.api.payments.payments_router import router as payments_router
from core.api.payments.receipts_router import router as receipts_router

# 🔥 XAFPay Webhook Router
from core.api.xafpay_webhook import router as xafpay_webhook_router


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
def kernel_db_check():
    return {"database": "connected"}


# ====================================================
# 🔐 ADMIN-ONLY TEST ENDPOINT (RBAC PROBE)
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

# 🔥 XAFPay Webhook → /kernel/payments/xafpay/webhook
# (Route inside webhook file MUST be: @router.post("/xafpay/webhook"))
kernel_router.include_router(
    xafpay_webhook_router,
    prefix="/payments",
    tags=["XafPay"],
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

kernel_router.include_router(
    accounting_router,
    prefix="/accounting",
    tags=["Accounting"],
)

kernel_router.include_router(
    orders_router,
    prefix="/orders",
    tags=["Orders"],
)