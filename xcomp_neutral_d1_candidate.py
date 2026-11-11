"""XBOS Complete D1 *candidate* ASGI entrypoint, not the production main:app.

Additive composition avoids changes to startup.py, an immutable historical PC8
artifact. This entrypoint has no credential, schema, payment or merchant activation
privileges. The neutral endpoints themselves fail closed without admitted live
browser-to-PC5 session binding and PA/PK repository dependencies.
"""
from __future__ import annotations

from fastapi import FastAPI


def build_candidate_app() -> FastAPI:
    from startup import create_app
    from platform_admin.neutral_d1_read_router import (
        router as neutral_d1_router, readiness_router as d1d2_readiness_router,
    )

    app = create_app()
    existing = {(path.path, method) for path in app.routes
                for method in getattr(path, "methods", ())}
    proposed = {(path.path, method) for path in neutral_d1_router.routes
                for method in getattr(path, "methods", ())}
    if existing & proposed:
        raise RuntimeError("D1_NEUTRAL_CANDIDATE_DUPLICATE_ROUTE")
    if len(proposed) != 3 or any(method != "GET" for _path, method in proposed):
        raise RuntimeError("D1_NEUTRAL_CANDIDATE_READ_ONLY_POLICY_CHANGED")
    readiness = {(path.path, method) for path in d1d2_readiness_router.routes
                 for method in getattr(path, "methods", ())}
    if len(readiness) != 1 or any(method != "GET" for _path, method in readiness):
        raise RuntimeError("D1D2_READINESS_CANDIDATE_READ_ONLY_POLICY_CHANGED")
    if (existing | proposed) & readiness:
        raise RuntimeError("D1D2_READINESS_CANDIDATE_DUPLICATE_ROUTE")
    app.include_router(neutral_d1_router)
    app.include_router(d1d2_readiness_router)
    return app


# Separate, explicit future ASGI import path. NOT referenced by main.py.
# Preserves existing DATABASE_URL fail-closed startup behavior.
app = build_candidate_app()
