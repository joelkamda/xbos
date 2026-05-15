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
        self.routes: Dict[Tuple[str, str], str] = {
            # ============================================================
            # SALES
            # ============================================================
            ("GET",  "/kernel/sales/"): "sale.view",
            ("POST", "/kernel/sales/"): "sale.create",

            # ============================================================
            # INVENTORY
            # ============================================================
            ("GET",  "/kernel/inventory/"): "inventory.view",
            ("POST", "/kernel/inventory/"): "inventory.edit",

            # ============================================================
            # ACCOUNTING / TREASURY - BASE
            # ============================================================
            ("GET",  "/kernel/accounting/"): "accounting.view",
            ("POST", "/kernel/accounting/"): "accounting.post",
            ("PUT",  "/kernel/accounting/{id}"): "accounting.edit",
            ("PATCH", "/kernel/accounting/{id}"): "accounting.edit",

            # ============================================================
            # ACCOUNTING / TREASURY - READ ROUTES
            # ============================================================
            ("GET", "/kernel/accounting/daily"): "accounting.view",
            ("GET", "/kernel/accounting/income"): "accounting.view",
            ("GET", "/kernel/accounting/expenses"): "accounting.view",
            ("GET", "/kernel/accounting/cash-moves"): "accounting.view",
            ("GET", "/kernel/accounting/debt"): "accounting.view",
            ("GET", "/kernel/accounting/reconciliation"): "accounting.view",
            ("GET", "/kernel/accounting/treasury"): "accounting.view",
            ("GET", "/kernel/accounting/init"): "accounting.view",

            # ============================================================
            # ACCOUNTING / TREASURY - CREATE ROUTES
            # ============================================================
            ("POST", "/kernel/accounting/income/manual"): "accounting.post",
            ("POST", "/kernel/accounting/expenses"): "accounting.post",
            ("POST", "/kernel/accounting/cash-movements"): "accounting.post",
            ("POST", "/kernel/accounting/reconciliation/close"): "accounting.reconcile",
            ("POST", "/kernel/accounting/reconciliation/save-draft"): "accounting.reconcile",

            # ============================================================
            # ACCOUNTING / TREASURY - EDIT ROUTES
            # ============================================================
            ("PATCH", "/kernel/accounting/income/manual/{event_id}"): "accounting.edit",
            ("PATCH", "/kernel/accounting/expenses/{event_id}"): "accounting.edit",
            ("PATCH", "/kernel/accounting/cash-movements/{event_id}"): "accounting.edit",

            # Support integer-normalized fallback in case route param is
            # normalized as {id} by older middleware/helpers.
            ("PATCH", "/kernel/accounting/income/manual/{id}"): "accounting.edit",
            ("PATCH", "/kernel/accounting/expenses/{id}"): "accounting.edit",
            ("PATCH", "/kernel/accounting/cash-movements/{id}"): "accounting.edit",

            # ============================================================
            # TAXONOMY
            # ============================================================
            ("GET", "/kernel/taxonomy/"): "taxonomy.view",
            ("GET", "/kernel/taxonomy/all"): "taxonomy.view",
            ("GET", "/kernel/taxonomy/{id}/children"): "taxonomy.view",

            ("POST",   "/kernel/taxonomy/"): "taxonomy.create",
            ("PUT",    "/kernel/taxonomy/{id}"): "taxonomy.edit",
            ("PATCH",  "/kernel/taxonomy/{id}"): "taxonomy.edit",
            ("DELETE", "/kernel/taxonomy/{id}"): "taxonomy.delete",

            # ============================================================
            # CATALOG
            # ============================================================
            ("GET",    "/kernel/catalog/"): "catalog.view",
            ("POST",   "/kernel/catalog/"): "catalog.create",
            ("PUT",    "/kernel/catalog/{id}"): "catalog.edit",
            ("PATCH",  "/kernel/catalog/{id}"): "catalog.edit",
            ("DELETE", "/kernel/catalog/{id}"): "catalog.delete",
        }

        self.compiled = []
        for (method, path), perm in self.routes.items():
            regex, _, _ = compile_path(path)
            self.compiled.append((method, regex, perm))

        self.ALL = self._build_all_permissions()

    def _build_all_permissions(self) -> set:
        all_codes = set()

        for perms in PERMISSION_GROUPS.values():
            for p in perms:
                all_codes.add(p)

        for name in dir(codes_module):
            if name.isupper():
                value = getattr(codes_module, name)
                if isinstance(value, str):
                    all_codes.add(value)

        # Safety patch for currently used DB permissions.
        # This prevents login failure if role rows already contain these permissions.
        all_codes.update({
            "accounting.view",
            "accounting.post",
            "accounting.edit",
            "accounting.reconcile",
            "accounting.export",
            "accounting.close_period",
            "order.update",
        })

        return all_codes

    def resolve(self, path: str, method: str) -> Optional[str]:
        method = method.upper().strip()
        normalized = self.normalize_path(path)

        if (method, normalized) in self.routes:
            return self.routes[(method, normalized)]

        for (m, regex, perm) in self.compiled:
            if m == method and regex.match(path):
                return perm

        return None

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

    def validate_permissions(self, perms: List[str]) -> List[str]:
        validated = []

        for p in perms:
            if p not in self.ALL:
                raise ValueError(f"Invalid permission code: {p}")

            validated.append(p)

        return validated


PERMISSION_REGISTRY = PermissionRegistry()


def is_valid_permission(code: str) -> bool:
    return code in PERMISSION_REGISTRY.ALL