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
# - LOW     → read / view / harmless actions
# - MEDIUM  → create / edit / operational writes
# - HIGH    → destructive, financial, irreversible actions
# ============================================================

PERMISSION_LEVELS = {

    # ----------------------------
    # SALES
    # ----------------------------
    "sale.view": LOW,
    "sale.create": LOW,
    "sale.edit": MEDIUM,
    "sale.refund": MEDIUM,

    # ----------------------------
    # INVENTORY
    # ----------------------------
    "inventory.view": LOW,
    "inventory.edit": MEDIUM,
    "inventory.adjust": MEDIUM,
    "inventory.transfer": HIGH,

    # ----------------------------
    # PAYMENTS
    # ----------------------------
    "payments.receive": LOW,
    "payments.send": MEDIUM,
    "payments.reconcile": HIGH,

    # ----------------------------
    # REPORTS (GENERIC + FINANCIAL)
    # ----------------------------
    "report.view": MEDIUM,
    "report.export": MEDIUM,
    "report.sales": MEDIUM,
    "report.financial": HIGH,
    "report.finance.view": HIGH,
    "report.financial.overview": HIGH,
    "report.financial.export": HIGH,
    "report.financial.audit": HIGH,

    # ----------------------------
    # ORDERS / POS
    # ----------------------------
    "order.view": LOW,
    "order.create": LOW,
    "order.update": MEDIUM,
    "order.update_status": MEDIUM,
    "order.delete": HIGH,
    "order.export": MEDIUM,

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
    # CATALOG (Billable Units)
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
}
