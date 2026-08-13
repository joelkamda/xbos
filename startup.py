# startup.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ------------------------------------------------------------
# Register models for compatibility consumers. Alembic owns canonical schema
# installation; application import must not execute database DDL or DML.
# ------------------------------------------------------------
import core.models_import

# ------------------------------------------------------------
# Core middleware
# ------------------------------------------------------------
from core.middleware.tenant_middleware import TenantMiddleware
from core.middleware.branch_middleware import BranchMiddleware
from core.middleware.auth_middleware import AuthMiddleware

# ------------------------------------------------------------
# RBAC imports (FINAL)
# ------------------------------------------------------------
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY
# ============================================================
# 1) DATABASE INITIALIZATION
# ============================================================
def init_database():
    """Compatibility-only explicit initializer; never run on app import."""
    from database import Base, engine
    Base.metadata.create_all(bind=engine)


# ============================================================
# 2) PERMISSION VALIDATION
# ============================================================
def validate_permissions() -> int:
    """Validate the in-process registry without writing to stdout or storage."""
    all_perms = PERMISSION_REGISTRY.ALL
    if not isinstance(all_perms, set):
        raise TypeError("PERMISSION_REGISTRY.ALL must be a set")
    return len(all_perms)


# ============================================================
# 3) RBAC SEEDING (LEVEL-BASED ONLY)
# ============================================================
def seed_rbac():
    """Compatibility-only legacy RBAC bootstrap; PC5 is canonical authority."""
    from database import SessionLocal
    from core.rbac.seeds.seed_roles import seed_roles
    from core.rbac.seeds.seed_role_permissions import seed_role_permissions

    print("🔐 Seeding RBAC (roles + level-based permissions)...")

    db = SessionLocal()
    try:
        seed_roles(db)
        seed_role_permissions(db)
    finally:
        db.close()

    print("✅ RBAC seeding complete")


# ============================================================
# 4) MIDDLEWARE REGISTRATION
# ============================================================
# startup.py
def register_middlewares(app: FastAPI):

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ❌ OLD (wrong execution order)
    # app.add_middleware(AuthMiddleware)
    # app.add_middleware(BranchMiddleware)
    # app.add_middleware(TenantMiddleware)

    # ✅ CORRECT ORDER (reverse execution logic)
    app.add_middleware(BranchMiddleware)
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware)


# ============================================================
# 5) REGISTER API ROUTES
# ============================================================
def register_routes(app: FastAPI):
    from core.api.kernel_router import kernel_router
    app.include_router(kernel_router)


# ============================================================
# 6) MAIN APPLICATION FACTORY
# ============================================================
def create_app() -> FastAPI:
    app = FastAPI(title="XBOS Kernel")

    # Pure contract validation only. Alembic installs schema and explicit
    # provisioning establishes data; importing main:app must require neither.
    validate_permissions()

    # Middleware (CORS FIRST)
    register_middlewares(app)

    # Routes
    register_routes(app)

    return app
