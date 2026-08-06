"""Alembic object-selection policy for additive canonical migration work."""

from __future__ import annotations

from typing import Any, Optional


LEGACY_ORM_TABLES = frozenset(
    {
        "accounts_receivable",
        "accounts_receivable_repayments",
        "atomic_unit_taxonomy",
        "atomic_units",
        "branches",
        "inventory_items",
        "inventory_movements",
        "order_item_modifiers",
        "order_items",
        "orders",
        "payment_attempts",
        "payment_intents",
        "payments",
        "recon_sheets",
        "roles",
        "sale_items",
        "sales",
        "taxonomy_nodes",
        "tenants",
        "treasury_logs",
        "users",
    }
)

LEGACY_DATABASE_ONLY_TABLES = frozenset(
    {
        "billable_unit_taxonomy",
        "idempotency_keys",
    }
)

STAGING_TABLES = frozenset(
    {
        "wnd_inventory_aliases",
        "wnd_inventory_real_staging",
        "wnd_inventory_staging",
    }
)

ALEMBIC_INTERNAL_TABLES = frozenset({"alembic_version"})

PROTECTED_EXISTING_TABLES = frozenset().union(
    LEGACY_ORM_TABLES,
    LEGACY_DATABASE_ONLY_TABLES,
    STAGING_TABLES,
    ALEMBIC_INTERNAL_TABLES,
)


def _owning_table_name(object_: Any, name: str, type_: str) -> Optional[str]:
    if type_ == "table":
        return str(name)

    table = getattr(object_, "table", None)
    table_name = getattr(table, "name", None)

    return str(table_name) if table_name is not None else None


def include_object(
    object_: Any,
    name: str,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """
    Exclude the observed compatibility schema from Alembic autogeneration.

    The exclusion applies to both reflected and metadata-side objects, including
    child columns, indexes and constraints. Handwritten migrations may still alter a
    protected table after a separate domain migration plan and approval. Any table
    not in the protected inventory remains visible, including new canonical tables.
    """

    del reflected, compare_to

    table_name = _owning_table_name(object_, name, type_)

    return table_name not in PROTECTED_EXISTING_TABLES
