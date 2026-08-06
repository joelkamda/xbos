"""
Explicit SQLAlchemy model-registration boundary for Alembic and schema audits.

Importing this module registers every authoritative ORM table currently owned by
the application. The duplicate historical ``core.domain.catalog.models`` module is
intentionally excluded; ``core.domain.inventory.models`` is the registered owner of
``inventory_items`` and ``inventory_movements`` until that module is migrated.
"""

from importlib import import_module


MODEL_MODULES = (
    "core.tenants.tenant_model",
    "core.users.user_model",
    "core.rbac.roles.role_model",
    "core.domain.taxonomy.models",
    "core.domain.orders.models",
    "core.domain.sales.models",
    "core.domain.payments.models",
    "core.domain.inventory.models",
    "core.domain.accounting.models",
    "core.domain.accounting.accounts_receivable.models",
)

EXCLUDED_DUPLICATE_MODEL_MODULES = (
    "core.domain.catalog.models",
)

IMPORTED_MODEL_MODULES = tuple(import_module(module_name) for module_name in MODEL_MODULES)

__all__ = [
    "EXCLUDED_DUPLICATE_MODEL_MODULES",
    "IMPORTED_MODEL_MODULES",
    "MODEL_MODULES",
]
