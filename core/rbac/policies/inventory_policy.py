# core/rbac/policies/inventory_policy.py

from core.rbac.policies.base_policy import BasePolicy


class InventoryPolicy(BasePolicy):

    def can_add_item(self):
        return self.has("INVENTORY.ADD_ITEM")

    def can_update_stock(self):
        return self.has("INVENTORY.UPDATE_STOCK")

    def can_delete_item(self):
        return self.has("INVENTORY.DELETE_ITEM")

    def can_view_inventory(self):
        return self.has("INVENTORY.VIEW")
