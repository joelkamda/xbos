# core/rbac/permissions/permission_groups.py

from .permission_codes import *

PERMISSION_GROUPS = {

    # ============================================================
    # SALES & POS SALES
    # ============================================================
    "sales": [
        SALE_VIEW,
        SALE_CREATE,
        SALE_EDIT,
        SALE_REFUND,
        SALE_CANCEL,
        SALE_VOID,
        SALE_DISCOUNT,
    ],

    # ============================================================
    # INVENTORY MANAGEMENT
    # ============================================================
    "inventory": [
        INV_VIEW,
        INV_EDIT,
        INV_ADJUST,
        INV_TRANSFER,
        INV_RECEIVE,
        INV_CONSUME,
        INV_RECONCILE,
    ],

    # ============================================================
    # PAYMENTS (Collections, Disbursements, Reconciliation)
    # ============================================================
    "payments": [
        PAY_VIEW,
        PAY_SEND,
        PAY_RECEIVE,
        PAY_REFUND,
        PAY_CANCEL,
        PAY_RECONCILE,
    ],

    # ============================================================
    # ACCOUNTING / TREASURY
    # ============================================================
    "accounting": [
        ACC_VIEW,
        ACC_POST,
        ACC_RECONCILE,
        ACC_EXPORT,
        ACC_CLOSE_PERIOD,
    ],

    # ============================================================
    # REPORTING & ANALYTICS
    # ============================================================
    "reports": [
        REPORT_VIEW,
        REPORT_EXPORT,
        REPORT_SALES,
        REPORT_FINANCE_VIEW,
        REPORT_FINANCIAL,
        REPORT_FINANCIAL_OVERVIEW,
        REPORT_FINANCIAL_EXPORT,
        REPORT_FINANCIAL_AUDIT,
    ],

    # ============================================================
    # POS / ORDER OPERATIONS
    # ============================================================
    "orders": [
        ORDER_VIEW,
        ORDER_CREATE,
        ORDER_UPDATE,
        ORDER_DELETE,
        ORDER_CANCEL,
        ORDER_UPDATE_STATUS,
        ORDER_EXPORT,
    ],

    # ============================================================
    # CATALOG / TAXONOMY
    # ============================================================
    "catalog": [
        CATALOG_VIEW,
        CATALOG_CREATE,
        CATALOG_EDIT,
        CATALOG_DELETE,
    ],

    "taxonomy": [
        TAXONOMY_VIEW,
        TAXONOMY_CREATE,
        TAXONOMY_EDIT,
        TAXONOMY_DELETE,
    ],

    # ============================================================
    # CUSTOMER MANAGEMENT
    # ============================================================
    "customers": [
        CUSTOMER_VIEW,
        CUSTOMER_CREATE,
        CUSTOMER_UPDATE,
        CUSTOMER_DELETE,
        CUSTOMER_VERIFY,
        CUSTOMER_EXPORT,
    ],

    # ============================================================
    # USER MANAGEMENT
    # ============================================================
    "users": [
        USER_VIEW,
        USER_CREATE,
        USER_EDIT,
        USER_DISABLE,
        USER_RESET_PASSWORD,
    ],

    # ============================================================
    # TRANSACTION MANAGEMENT
    # ============================================================
    "transactions": [
        TRANSACTION_VIEW,
        TRANSACTION_CREATE,
        TRANSACTION_UPDATE,
        TRANSACTION_DELETE,
        TRANSACTION_EXPORT,
    ],

    # ============================================================
    # WALLET MANAGEMENT
    # ============================================================
    "wallet": [
        WALLET_BALANCE_VIEW,
        WALLET_BALANCE_ADJUST,
        WALLET_TRANSACTION_VIEW,
        WALLET_TRANSACTION_EXPORT,
        WALLET_FREEZE,
        WALLET_UNFREEZE,
    ],

    # ============================================================
    # HUMAN RESOURCES
    # ============================================================
    "hr": [
        HR_VIEW,
        HR_EDIT,
    ],

    # ============================================================
    # RBAC / SYSTEM ADMINISTRATION
    # ============================================================
    "rbac": [
        RBAC_ROLE_VIEW,
        RBAC_ROLE_EDIT,
        RBAC_PERMISSION_VIEW,
    ],

    "system": [
        SYSTEM_SETTINGS_VIEW,
        SYSTEM_SETTINGS_EDIT,
    ],
}