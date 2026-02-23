# core/rbac/policies/payments_policy.py

from core.rbac.policies.base_policy import BasePolicy


class PaymentsPolicy(BasePolicy):

    def can_initiate_payout(self):
        return self.has("PAYMENTS.SEND_PAYOUT")

    def can_refund(self):
        return self.has("PAYMENTS.ISSUE_REFUND")

    def can_view_transactions(self):
        return self.has("PAYMENTS.VIEW_TRANSACTIONS")
