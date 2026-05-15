# core/rbac/permissions/permission_levels.py

# ============================================================
# PERMISSION SEVERITY LEVELS
# ============================================================

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"

LEVEL_ORDER = {
    LOW: 1,
    MEDIUM: 2,
    HIGH: 3,
}

# ============================================================
# PERMISSION → LEVEL MAPPING
# ============================================================
# Rule of thumb:
# - LOW     → read / view / harmless frontline actions
# - MEDIUM  → create / edit / operational writes
# - HIGH    → destructive, financial, irreversible, admin actions
# ============================================================

PERMISSION_LEVELS = {

    # ----------------------------
    # SALES
    # ----------------------------
    "sale.view": LOW,
    "sale.create": LOW,
    "sale.edit": MEDIUM,
    "sale.refund": HIGH,
    "sale.cancel": MEDIUM,
    "sale.void": HIGH,
    "sale.discount": MEDIUM,

    # ----------------------------
    # INVENTORY
    # ----------------------------
    "inventory.view": LOW,
    "inventory.edit": MEDIUM,
    "inventory.adjust": MEDIUM,
    "inventory.transfer": HIGH,
    "inventory.receive": MEDIUM,
    "inventory.consume": MEDIUM,
    "inventory.reconcile": HIGH,

    # ----------------------------
    # PAYMENTS
    # ----------------------------
    "payments.view": LOW,
    "payments.receive": LOW,
    "payments.send": MEDIUM,
    "payments.refund": HIGH,
    "payments.cancel": MEDIUM,
    "payments.reconcile": HIGH,

    # ----------------------------
    # ACCOUNTING / TREASURY
    # ----------------------------
    "accounting.view": MEDIUM,
    "accounting.post": MEDIUM,
    "accounting.reconcile": HIGH,
    "accounting.export": HIGH,
    "accounting.close_period": HIGH,
    "accounting.edit": HIGH,

    # ----------------------------
    # REPORTS (GENERIC + FINANCIAL)
    # ----------------------------
    "report.view": MEDIUM,
    "report.export": MEDIUM,
    "report.sales": MEDIUM,
    "report.finance.view": HIGH,
    "report.financial": HIGH,
    "report.financial.overview": HIGH,
    "report.financial.export": HIGH,
    "report.financial.audit": HIGH,

    # ----------------------------
    # ORDERS / POS
    # ----------------------------
    "order.view": LOW,
    "order.create": LOW,
    "order.update": MEDIUM,
    "order.delete": HIGH,
    "order.cancel": MEDIUM,
    "order.update_status": MEDIUM,
    "order.export": MEDIUM,

    # ----------------------------
    # CATALOG (Atomic Units)
    # ----------------------------
    "catalog.view": LOW,
    "catalog.create": MEDIUM,
    "catalog.edit": MEDIUM,
    "catalog.delete": HIGH,

    # ----------------------------
    # TAXONOMY (Structure / Classification)
    # ----------------------------
    "taxonomy.view": LOW,
    "taxonomy.create": MEDIUM,
    "taxonomy.edit": MEDIUM,
    "taxonomy.delete": HIGH,

    # ----------------------------
    # CUSTOMERS
    # ----------------------------
    "customer.view": LOW,
    "customer.create": MEDIUM,
    "customer.update": MEDIUM,
    "customer.delete": HIGH,
    "customer.verify": MEDIUM,
    "customer.export": MEDIUM,

    # ----------------------------
    # USER MANAGEMENT
    # ----------------------------
    "user.view": HIGH,
    "user.create": HIGH,
    "user.edit": HIGH,
    "user.disable": HIGH,
    "user.reset_password": HIGH,

    # ----------------------------
    # TRANSACTIONS
    # ----------------------------
    "transaction.view": LOW,
    "transaction.create": MEDIUM,
    "transaction.update": MEDIUM,
    "transaction.delete": HIGH,
    "transaction.export": MEDIUM,

    # ----------------------------
    # WALLET
    # ----------------------------
    "wallet.balance.view": LOW,
    "wallet.balance.adjust": HIGH,
    "wallet.transaction.view": LOW,
    "wallet.transaction.export": MEDIUM,
    "wallet.freeze": HIGH,
    "wallet.unfreeze": HIGH,

    # ----------------------------
    # HUMAN RESOURCES
    # ----------------------------
    "hr.view": MEDIUM,
    "hr.edit": HIGH,

    # ----------------------------
    # RBAC / SYSTEM ADMINISTRATION
    # ----------------------------
    "rbac.role.view": HIGH,
    "rbac.role.edit": HIGH,
    "rbac.permission.view": HIGH,

    "system.settings.view": HIGH,
    "system.settings.edit": HIGH,
}