"""
Compatibility exports for legacy catalog imports.

Inventory persistence authority lives exclusively in:
    core.domain.inventory.models

Do not declare inventory_items or inventory_movements ORM tables here.
Catalog owns AtomicUnit/taxonomy discovery; Inventory owns stock state/ledger.
"""

from core.domain.inventory.models import InventoryItem, InventoryMovement

__all__ = ["InventoryItem", "InventoryMovement"]
