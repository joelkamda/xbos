# startup.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine, SessionLocal

# ------------------------------------------------------------
# Load ALL SQLAlchemy models so metadata.create_all() sees them
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
from core.rbac.seeds.seed_roles import seed_roles
from core.rbac.seeds.seed_role_permissions import seed_role_permissions


# ============================================================
# 1) DATABASE INITIALIZATION
# ============================================================
def init_database():
    Base.metadata.create_all(bind=engine)


# ============================================================
# 2) PERMISSION VALIDATION
# ============================================================
def validate_permissions():
    print("🔍 Validating RBAC permissions...")

    all_perms = PERMISSION_REGISTRY.ALL
    if not isinstance(all_perms, set):
        raise TypeError("PERMISSION_REGISTRY.ALL must be a set")

    print(f"✅ Permission registry OK ({len(all_perms)} permissions)")


# ============================================================
# 3) RBAC SEEDING (LEVEL-BASED ONLY)
# ============================================================
def seed_rbac():
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

    # 1) DB schema
    init_database()

    # 2) Permission sanity check
    validate_permissions()

    # 3) RBAC bootstrap (CANONICAL)
    seed_rbac()

    # 4) Middleware (CORS FIRST)
    register_middlewares(app)

    # 5) Routes
    register_routes(app)

    return app
