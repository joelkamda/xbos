# core/rbac/policies/accounting_policy.py

from core.rbac.policies.base_policy import BasePolicy


class AccountingPolicy(BasePolicy):

    def can_view_reports(self):
        return self.has("FINANCE.VIEW_REPORT")

    def can_edit_entries(self):
        return self.has("FINANCE.EDIT_ENTRY")

    def can_close_period(self):
        return self.has("FINANCE.CLOSE_PERIOD")
