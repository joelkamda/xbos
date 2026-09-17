"""R6.5 WND compatibility runtime entrypoint.

This is an explicit temporary hypercare composition. Compatibility routes are
registered before the legacy core routers so accepted static WND paths such as
``/kernel/payments/activity`` cannot be shadowed by older dynamic routes such
as ``/kernel/payments/{payment_id}``. Neutral ``main:app`` remains unchanged.
"""
from fastapi import FastAPI

from startup import register_middlewares, validate_permissions
from core.api.kernel_router import kernel_router
from restaurant.r6.wnd_api_compat import router as wnd_r6_compat_router

app = FastAPI(title="XBOS Kernel — WND R6 Compatibility Hypercare")
validate_permissions()
register_middlewares(app)

# Precedence is deliberate: compatibility static routes must win over legacy
# dynamic catch-all routes during WND hypercare.
app.include_router(wnd_r6_compat_router)
app.include_router(kernel_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "kernel": "online",
        "version": "1.0.0",
        "runtime": "wnd-r6-compat-hypercare",
    }
