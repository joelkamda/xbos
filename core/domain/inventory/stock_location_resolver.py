"""Canonical application-side SO3 stock-location resolution.

R6.5-LR2 successor-writer remediation.

This module replaces legacy R63 trigger-side stock-location autofill with an
application-owned, fail-closed resolver. It does not create stock locations,
does not infer stock-location identity from branch_id, and does not accept
stock-location identity from an untrusted caller.

Authority chain:
    (tenant_id, branch_id)
      -> legacy_branch_structural_mappings.location_id
      -> so3_stock_locations.id for the same tenant/location

The mapping is accepted compatibility structure. The SO3 row remains the
canonical stock-location identity.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def resolve_canonical_stock_location_id(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
) -> int:
    """Return exactly one canonical SO3 stock-location id, or fail closed."""

    rows = (
        db.execute(
            text(
                """
                SELECT sl.id
                FROM legacy_branch_structural_mappings AS m
                JOIN so3_stock_locations AS sl
                  ON sl.tenant_id = m.tenant_id
                 AND sl.location_id = m.location_id
                WHERE m.tenant_id = :tenant_id
                  AND m.branch_id = :branch_id
                ORDER BY sl.id
                """
            ),
            {
                "tenant_id": int(tenant_id),
                "branch_id": int(branch_id),
            },
        )
        .scalars()
        .all()
    )

    unique_ids = sorted({int(value) for value in rows if value is not None})

    if len(unique_ids) != 1:
        raise ValueError(
            "Canonical SO3 stock-location resolution failed closed for "
            f"tenant_id={tenant_id}, branch_id={branch_id}: "
            f"expected exactly one stock location, found {len(unique_ids)}"
        )

    return unique_ids[0]


def validate_inventory_item_stock_location(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    inventory_item_stock_location_id: int | None,
) -> int:
    """Validate an item's persisted stock location against canonical SO3 truth."""

    canonical_id = resolve_canonical_stock_location_id(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
    )

    actual_id = (
        int(inventory_item_stock_location_id)
        if inventory_item_stock_location_id is not None
        else None
    )

    if actual_id != canonical_id:
        raise ValueError(
            "Inventory item stock-location authority mismatch for "
            f"tenant_id={tenant_id}, branch_id={branch_id}: "
            f"item={actual_id}, canonical={canonical_id}"
        )

    return canonical_id