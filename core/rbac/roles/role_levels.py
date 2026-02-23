LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"

ROLE_DEFAULT_LEVEL = {

    # ============================================================
    # FRONTLINE / STAFF (LEVEL 1)
    # ============================================================
    # Rule: execute operations, no authority to alter systems
    # ============================================================

    "cashier": LOW,
    "waiter": LOW,
    "sales_rep": LOW,
    "inventory_clerk": LOW,
    "storekeeper": LOW,
    "pos_operator": LOW,
    "kitchen_staff": LOW,        # restaurant
    "nurse": LOW,                # clinic (ops-only)
    "pharmacy_assistant": LOW,

    # ============================================================
    # SUPERVISORY / MANAGEMENT (LEVEL 2)
    # ============================================================
    # Rule: manage people, stock, workflows; limited financial power
    # ============================================================

    "shift_supervisor": MEDIUM,
    "store_manager": MEDIUM,
    "branch_manager": MEDIUM,
    "inventory_manager": MEDIUM,
    "operations_manager": MEDIUM,
    "sales_manager": MEDIUM,
    "customer_support": MEDIUM,

    # ============================================================
    # FINANCE / CONTROL (LEVEL 2 or 3 depending on trust model)
    # ============================================================

    "accountant": MEDIUM,
    "bookkeeper": MEDIUM,
    "auditor": HIGH,              # audit must override ops
    "finance_manager": HIGH,

    # ============================================================
    # EXECUTIVE / OWNERSHIP (LEVEL 3)
    # ============================================================
    # Rule: irreversible, financial, governance actions
    # ============================================================

    "owner": HIGH,
    "founder": HIGH,
    "executive": HIGH,
    "director": HIGH,

    # ============================================================
    # PLATFORM / SYSTEM (LEVEL 3)
    # ============================================================

    "admin": HIGH,
    "super_admin": HIGH,
    "system": HIGH,
}
