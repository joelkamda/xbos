"""D1 *isolated candidate*, deliberately not a hosted admission or operative API.

No legacy XBOS startup, database connection, session signing or payment routes.
All neutral tenant reads retain the existing fail-closed browser-to-PC5 dependency.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from platform_admin.neutral_d1_read_router import (
    router as neutral_router,
    readiness_router as neutral_readiness_router,
)

EXPECTED = {
    ("GET", "/kernel/neutral/v1/tenants/{tenant_id}/branches/{branch_id}/context"),
    ("GET", "/kernel/neutral/v1/tenants/{tenant_id}/commercial-entitlements"),
    ("GET", "/kernel/neutral/v1/tenants/{tenant_id}/packs/{pack_code}/state"),
    ("GET", "/platform/xcomp/d1d2/readiness"),
}


def build_isolated_candidate() -> FastAPI:
    app = FastAPI(
        title="XCOMP D1 isolated nonoperative source candidate",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.include_router(neutral_router)
    app.include_router(neutral_readiness_router)

    business_routes = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", ()) or ())
    }
    if business_routes != EXPECTED:
        raise RuntimeError("D1_ISOLATED_APP_UNEXPECTED_BUSINESS_ROUTE")

    @app.get("/health/process", include_in_schema=False)
    def process_liveness():
        return {"process": "alive", "d1_authenticated": False, "admitted": False}

    @app.get("/health/ready", include_in_schema=False)
    def denied_until_live_admission():
        raise HTTPException(status_code=503, detail="D1_HOSTED_ADMISSION_NOT_ESTABLISHED")

    return app


app = build_isolated_candidate()
