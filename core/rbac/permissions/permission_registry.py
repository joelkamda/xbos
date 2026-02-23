# core/rbac/permissions/permission_registry.py

from typing import Dict, Tuple, Optional, List
from fastapi.routing import compile_path

from .permission_groups import PERMISSION_GROUPS
from . import permission_codes as codes_module


class PermissionRegistry:
    """
    Central RBAC registry linking routes → permissions.

    Provides:
        - Static route mapping
        - Dynamic path regex matching
        - Permission validation
    """

    def __init__(self):
        # =====================================================
        # STATIC ROUTE MAP (Tier-0 explicit)
        # =====================================================
        self.routes: Dict[Tuple[str, str], str] = {

            # ----------------------------
            # SALES
            # ----------------------------
            ("GET",  "/kernel/sales/"): "sale.view",
            ("POST", "/kernel/sales/"): "sale.create",

            # ----------------------------
            # INVENTORY
            # ----------------------------
            ("GET",  "/kernel/inventory/"): "inventory.view",
            ("POST", "/kernel/inventory/"): "inventory.edit",

            # ----------------------------
            # TAXONOMY (Catalog structure)
            # ----------------------------
            ("GET", "/kernel/taxonomy/"): "taxonomy.view",
            ("GET", "/kernel/taxonomy/all"): "taxonomy.view",
            ("GET", "/kernel/taxonomy/{id}/children"): "taxonomy.view",

            ("POST",   "/kernel/taxonomy/"): "taxonomy.create",
            ("PUT",    "/kernel/taxonomy/{id}"): "taxonomy.edit",
            ("DELETE", "/kernel/taxonomy/{id}"): "taxonomy.delete",

            # ----------------------------
            # CATALOG (Billable Units)
            # ----------------------------
            ("GET",  "/kernel/catalog/"): "catalog.view",
            ("POST", "/kernel/catalog/"): "catalog.create",
            ("PUT",  "/kernel/catalog/{id}"): "catalog.edit",
            ("DELETE", "/kernel/catalog/{id}"): "catalog.delete",
        }

        # =====================================================
        # COMPILED DYNAMIC ROUTES
        # =====================================================
        self.compiled = []
        for (method, path), perm in self.routes.items():
            regex, _, _ = compile_path(path)
            self.compiled.append((method, regex, perm))

        # =====================================================
        # ALL VALID PERMISSIONS
        # =====================================================
        self.ALL = self._build_all_permissions()

    # ---------------------------------------------------------
    # Build full permission list
    # ---------------------------------------------------------
    def _build_all_permissions(self) -> set:
        all_codes = set()

        # 1) From permission groups
        for perms in PERMISSION_GROUPS.values():
            for p in perms:
                all_codes.add(p)

        # 2) From permission_codes module (single source of truth)
        for name in dir(codes_module):
            if name.isupper():
                value = getattr(codes_module, name)
                if isinstance(value, str):
                    all_codes.add(value)

        return all_codes

    # ---------------------------------------------------------
    # Resolve permission required for a request
    # ---------------------------------------------------------
    def resolve(self, path: str, method: str) -> Optional[str]:
        method = method.upper().strip()
        normalized = self.normalize_path(path)

        # Static match
        if (method, normalized) in self.routes:
            return self.routes[(method, normalized)]

        # Dynamic regex match
        for (m, regex, perm) in self.compiled:
            if m == method and regex.match(path):
                return perm

        return None  # Public / unprotected route

    # ---------------------------------------------------------
    # Normalize path for matching
    # ---------------------------------------------------------
    @staticmethod
    def normalize_path(path: str) -> str:
        parts = path.strip("/").split("/")
        normalized = []

        for p in parts:
            if p.isdigit():
                normalized.append("{id}")
            else:
                normalized.append(p)

        return "/" + "/".join(normalized)

    # ---------------------------------------------------------
    # Validate permissions (used during seeding)
    # ---------------------------------------------------------
    def validate_permissions(self, perms: List[str]) -> List[str]:
        validated = []
        for p in perms:
            if p not in self.ALL:
                raise ValueError(f"Invalid permission code: {p}")
            validated.append(p)
        return validated


# =========================================================
# SINGLETON
# =========================================================
PERMISSION_REGISTRY = PermissionRegistry()


# =========================================================
# Helper
# =========================================================
def is_valid_permission(code: str) -> bool:
    return code in PERMISSION_REGISTRY.ALL
