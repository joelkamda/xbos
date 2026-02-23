# core/auth/auth_service.py

from core.auth.password_service import PasswordService
from core.security.jwt_service import JWTService
from core.users.user_repository import UserRepository
from core.tenants.tenant_repository import TenantRepository
from core.tenants.branch_repository import BranchRepository
from core.errors.api_error import APIError

# RBAC imports
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY

# 🔐 LEVEL SYSTEM (PRIMARY)
from core.rbac.config import USE_PERMISSION_LEVELS
from core.rbac.permissions.permission_resolver import resolve_permissions_for_role

# 🧯 LEGACY ROLE PACKS (FALLBACK ONLY)
from core.rbac.roles.role_packs import ROLE_PACKS


class AuthService:
    def __init__(self):
        self.password_service = PasswordService()
        self.jwt_service = JWTService()
        self.users = UserRepository()

    # -------------------------------------------------------------------
    # MULTI-TENANT LOGIN + RBAC PERMISSION EXTRACTION
    # -------------------------------------------------------------------
    def login(self, db, username: str, password: str, tenant_code: str, branch_code: str):

        #1️⃣ Tenant validation
        tenant = TenantRepository.find_by_code(db, tenant_code)
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")

        # 2️⃣ Branch validation
        branch = BranchRepository.find_by_code(db, branch_code)
        if not branch or branch.tenant_id != tenant.id:
            raise APIError("BRANCH_NOT_FOUND")

        # 3️⃣ User lookup
        user = self.users.find_by_username(db, username)
        if not user:
            raise APIError("INVALID_CREDENTIALS")

        # 4️⃣ Password validation
        if not self.password_service.verify(password, user.password_hash):
            raise APIError("INVALID_CREDENTIALS")

        # 5️⃣ Active check
        if not user.is_active:
            raise APIError("USER_DISABLED")

        # 6️⃣ Tenant / branch match
        if user.tenant_id != tenant.id:
            raise APIError("USER_TENANT_MISMATCH")
        if user.branch_id != branch.id:
            raise APIError("USER_BRANCH_MISMATCH")

        # -------------------------------------------------------------------
        # 7️⃣ RBAC PERMISSIONS (LEVEL SYSTEM → FALLBACK ROLE PACKS)
        # -------------------------------------------------------------------
        if USE_PERMISSION_LEVELS:
            role_permissions = resolve_permissions_for_role(user.role)
            print(f"🔐 LEVEL-BASED PERMS for '{user.role}': {role_permissions}")
        else:
            role_permissions = ROLE_PACKS.get(user.role, [])
            print(f"🔐 PACK-BASED PERMS for '{user.role}': {role_permissions}")

        # User-level overrides (future-safe)
        custom_permissions = []
        if not isinstance(custom_permissions, list):
            custom_permissions = []

        # Merge + dedupe
        merged_permissions = sorted(set(role_permissions + custom_permissions))

        # Validate against registry
        merged_permissions = PERMISSION_REGISTRY.validate_permissions(merged_permissions)

        # -------------------------------------------------------------------
        # 8️⃣ TOKEN CREATION
        # -------------------------------------------------------------------
        access_token = self.jwt_service.create_access_token(
            user.id,
            tenant_id=user.tenant_id,
            branch_id=user.branch_id,
            role=user.role,
            permissions=merged_permissions,
            expires_minutes=60,
        )

        refresh_token = self.jwt_service.create_refresh_token(
            user.id,
            expires_days=30
        )

        # -------------------------------------------------------------------
        # 9️⃣ RESPONSE
        # -------------------------------------------------------------------
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "tenant_id": user.tenant_id,
                "branch_id": user.branch_id,
                "tenant_code": tenant_code,
                "branch_code": branch_code,
                "permissions": merged_permissions,
            },
        }

    # -------------------------------------------------------------------
    # REFRESH TOKEN
    # -------------------------------------------------------------------
    def refresh(self, db, refresh_token: str):

        payload = self.jwt_service.decode_token(refresh_token)

        user_id = int(payload["sub"])
        user = self.users.find_by_id(db, user_id)
        if not user:
            raise APIError("USER_NOT_FOUND")

        if USE_PERMISSION_LEVELS:
            role_permissions = resolve_permissions_for_role(user.role)
        else:
            role_permissions = ROLE_PACKS.get(user.role, [])

        merged_permissions = PERMISSION_REGISTRY.validate_permissions(role_permissions)

        new_access_token = self.jwt_service.create_access_token(
            user.id,
            tenant_id=user.tenant_id,
            branch_id=user.branch_id,
            role=user.role,
            permissions=merged_permissions,
            expires_minutes=60,
        )

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
        }
