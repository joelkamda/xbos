# core/rbac/policies/sales_policy.py

from .base_policy import BasePolicy
from core.rbac.permissions.permission_codes import *

class SalesPolicy(BasePolicy):

    def can_create_sale(self):
        return self.can(SALE_CREATE)

    def can_edit_sale(self):
        return self.can(SALE_EDIT)

    def can_refund(self):
        return self.can(SALE_REFUND)
