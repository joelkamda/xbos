# ============================================================
# STANDARDIZED PERMISSION CODES FOR XBOS RBAC
# ============================================================


# ----------------------------
# SALES
# ----------------------------
SALE_VIEW          = "sale.view"
SALE_CREATE        = "sale.create"
SALE_EDIT          = "sale.edit"
SALE_REFUND        = "sale.refund"
SALE_CANCEL        = "sale.cancel"
SALE_VOID          = "sale.void"
SALE_DISCOUNT      = "sale.discount"


# ----------------------------
# INVENTORY
# ----------------------------
INV_VIEW           = "inventory.view"
INV_EDIT           = "inventory.edit"
INV_ADJUST         = "inventory.adjust"
INV_TRANSFER       = "inventory.transfer"
INV_RECEIVE        = "inventory.receive"
INV_CONSUME        = "inventory.consume"
INV_RECONCILE      = "inventory.reconcile"


# ----------------------------
# PAYMENTS
# ----------------------------
PAY_VIEW           = "payments.view"
PAY_SEND           = "payments.send"
PAY_RECEIVE        = "payments.receive"
PAY_REFUND         = "payments.refund"
PAY_CANCEL         = "payments.cancel"
PAY_RECONCILE      = "payments.reconcile"


# ----------------------------
# ACCOUNTING / TREASURY
# ----------------------------
ACC_VIEW           = "accounting.view"
ACC_POST           = "accounting.post"
ACC_EDIT           = "accounting.edit"
ACC_RECONCILE      = "accounting.reconcile"
ACC_EXPORT         = "accounting.export"
ACC_CLOSE_PERIOD   = "accounting.close_period"

# ----------------------------
# REPORTS (GENERIC + DOMAIN)
# ----------------------------
REPORT_VIEW               = "report.view"
REPORT_EXPORT             = "report.export"
REPORT_SALES              = "report.sales"

REPORT_FINANCE_VIEW       = "report.finance.view"
REPORT_FINANCIAL          = "report.financial"
REPORT_FINANCIAL_OVERVIEW = "report.financial.overview"
REPORT_FINANCIAL_EXPORT   = "report.financial.export"
REPORT_FINANCIAL_AUDIT    = "report.financial.audit"


# ----------------------------
# POS / ORDER OPERATIONS
# ----------------------------
ORDER_VIEW            = "order.view"
ORDER_CREATE          = "order.create"
ORDER_UPDATE          = "order.update"
ORDER_DELETE          = "order.delete"
ORDER_CANCEL          = "order.cancel"
ORDER_UPDATE_STATUS   = "order.update_status"
ORDER_EXPORT          = "order.export"


# ----------------------------
# CATALOG / TAXONOMY
# ----------------------------
CATALOG_VIEW        = "catalog.view"
CATALOG_CREATE      = "catalog.create"
CATALOG_EDIT        = "catalog.edit"
CATALOG_DELETE      = "catalog.delete"

TAXONOMY_VIEW       = "taxonomy.view"
TAXONOMY_CREATE     = "taxonomy.create"
TAXONOMY_EDIT       = "taxonomy.edit"
TAXONOMY_DELETE     = "taxonomy.delete"


# ----------------------------
# CUSTOMER MANAGEMENT
# ----------------------------
CUSTOMER_VIEW       = "customer.view"
CUSTOMER_CREATE     = "customer.create"
CUSTOMER_UPDATE     = "customer.update"
CUSTOMER_DELETE     = "customer.delete"
CUSTOMER_VERIFY     = "customer.verify"
CUSTOMER_EXPORT     = "customer.export"


# ----------------------------
# USER MANAGEMENT
# ----------------------------
USER_VIEW           = "user.view"
USER_CREATE         = "user.create"
USER_EDIT           = "user.edit"
USER_DISABLE        = "user.disable"
USER_RESET_PASSWORD = "user.reset_password"


# ----------------------------
# TRANSACTION MANAGEMENT
# ----------------------------
TRANSACTION_VIEW      = "transaction.view"
TRANSACTION_CREATE    = "transaction.create"
TRANSACTION_UPDATE    = "transaction.update"
TRANSACTION_DELETE    = "transaction.delete"
TRANSACTION_EXPORT    = "transaction.export"


# ----------------------------
# WALLET MANAGEMENT
# ----------------------------
WALLET_BALANCE_VIEW        = "wallet.balance.view"
WALLET_BALANCE_ADJUST      = "wallet.balance.adjust"
WALLET_TRANSACTION_VIEW    = "wallet.transaction.view"
WALLET_TRANSACTION_EXPORT  = "wallet.transaction.export"
WALLET_FREEZE              = "wallet.freeze"
WALLET_UNFREEZE            = "wallet.unfreeze"


# ----------------------------
# HR
# ----------------------------
HR_VIEW           = "hr.view"
HR_EDIT           = "hr.edit"


# ----------------------------
# RBAC / SYSTEM ADMIN
# ----------------------------
RBAC_ROLE_VIEW        = "rbac.role.view"
RBAC_ROLE_EDIT        = "rbac.role.edit"
RBAC_PERMISSION_VIEW  = "rbac.permission.view"

SYSTEM_SETTINGS_VIEW  = "system.settings.view"
SYSTEM_SETTINGS_EDIT  = "system.settings.edit"