# core/rbac/roles/role_packs.py

from core.rbac.permissions.permission_groups import PERMISSION_GROUPS
from core.rbac.permissions.permission_codes import *

# SIMPLE DIRECT ROLE → PERMISSIONS MAPPING
ROLE_PACKS = {

    "cashier": [
        SALE_CREATE,
        SALE_VIEW,
        PAY_RECEIVE,
    ],

    "inventory_clerk": list(PERMISSION_GROUPS["inventory"]),

    "store_manager": list(
        PERMISSION_GROUPS["sales"]
        + PERMISSION_GROUPS["inventory"]
        + PERMISSION_GROUPS["reports"]
    ),

    "accountant": list(PERMISSION_GROUPS["accounting"]),
}
