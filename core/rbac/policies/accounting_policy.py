# core/rbac/policies/accounting_policy.py

"""
Accounting RBAC Policy

Controls access to the XBOS Accounting / Treasury module.

This policy protects:
• financial reports
• treasury ledger (treasury_logs)
• accounting adjustments
• reconciliation workflows
• accounting period closing
"""

from core.rbac.permissions.permission_decorator import require_permission
from core.rbac.permissions.permission_codes import (
    ACCOUNTING_VIEW,
    ACCOUNTING_POST,
    ACCOUNTING_RECONCILE,
    ACCOUNTING_EXPORT,
    ACCOUNTING_CLOSE_PERIOD,
)


class AccountingPolicy:

    # -------------------------------------------------
    # VIEW ACCOUNTING DATA
    # -------------------------------------------------

    @staticmethod
    @require_permission(ACCOUNTING_VIEW)
    def can_view(*args, **kwargs):
        """
        Allows viewing accounting data:
        - financial reports
        - treasury logs
        - reconciliation screens
        """
        return True


    # -------------------------------------------------
    # POST ACCOUNTING ENTRIES
    # -------------------------------------------------

    @staticmethod
    @require_permission(ACCOUNTING_POST)
    def can_post(*args, **kwargs):
        """
        Allows posting accounting entries:
        - manual adjustments
        - journal entries
        - corrections
        """
        return True


    # -------------------------------------------------
    # RECONCILIATION
    # -------------------------------------------------

    @staticmethod
    @require_permission(ACCOUNTING_RECONCILE)
    def can_reconcile(*args, **kwargs):
        """
        Allows treasury reconciliation:
        - verifying payment attempts
        - reconciling cash / MoMo / wallet
        - marking financial events as reconciled
        """
        return True


    # -------------------------------------------------
    # EXPORT REPORTS
    # -------------------------------------------------

    @staticmethod
    @require_permission(ACCOUNTING_EXPORT)
    def can_export(*args, **kwargs):
        """
        Allows exporting accounting data:
        - CSV
        - Excel
        - audit exports
        """
        return True


    # -------------------------------------------------
    # CLOSE ACCOUNTING PERIOD
    # -------------------------------------------------

    @staticmethod
    @require_permission(ACCOUNTING_CLOSE_PERIOD)
    def can_close_period(*args, **kwargs):
        """
        Allows closing an accounting period.

        After closing:
        • no more entries can be posted
        • ledger becomes immutable
        """
        return True