"""R6.0/R6.1 frozen WND reference-release baseline and rehearsal constants."""
from __future__ import annotations

PRODUCTION_DATABASE = "xbos"
SOURCE_DATABASE = "xbos_r6_1_source"
CANDIDATE_DATABASE = "xbos_r6_1_candidate"
DISPOSABLE_DATABASES = frozenset({SOURCE_DATABASE, CANDIDATE_DATABASE})

SOURCE_REVISION = "5c706797029a"
CANONICAL_SOURCE_STAMP = "m13_source_state_001"
TARGET_HEAD = "r2_restaurant_menu_fulfillment_043"

PRODUCTION_TENANT_ID = 2
PRODUCTION_BRANCH_ID = 1

REFERENCE_RELEASE_TAG = "wnd-track-a-reference-release-20260821"
PRODUCTION_BACKEND_RELEASE_BRANCH = "track-a/wnd-live-parity-reference-backend"
PRODUCTION_FRONTEND_RELEASE_BRANCH = "track-a/wnd-ui-live-parity-responsive-frontend"
REFERENCE_SOURCE_EVIDENCE_SHA256 = "fc291ec6c43507a9312d032ce61d5d4aee8db874377481a114d6785456242cc0"

SERVER_BACKUP_SHA256 = "22c105224f65dec2bc09ef0335748a1db855ee59945c170b69526ee18f39dc16"
SERVER_BACKUP_SIZE = 3679584
SERVER_BACKUP_FILENAME = "WND_R6_0_SERVER_PRODUCTION_SNAPSHOT_20260821_171736.backup"

PRODUCTION_BACKEND_HEAD = "b60a71dcc06657bd407fac043f6f3922d5bfe32f"
PRODUCTION_FRONTEND_HEAD = "f47f574f6a2f2e2247ab7c491dc65c7800adbc9d"
PRODUCTION_BACKEND_TAG = REFERENCE_RELEASE_TAG

EXPECTED_COUNTS = {'tenants': 3, 'branches': 4, 'users': 18, 'atomic_units': 813, 'taxonomy_nodes': 249, 'atomic_unit_taxonomy': 1008, 'customers': 0, 'orders': 8451, 'order_items': 17958, 'order_item_modifiers': 4010, 'sales': 7745, 'sale_items': 16566, 'accounts_receivable': 240, 'accounts_receivable_repayments': 13, 'payment_intents': 8115, 'payment_attempts': 7807, 'inventory_items': 176, 'inventory_movements': 38900, 'recon_sheets': 791, 'treasury_logs': 17490}

KITCHEN_BON_PRESERVATION = (
    "initial full kitchen print; edited orders print only semantic ADD/CANCEL/CHANGE deltas; "
    "non-semantic signature changes update watcher state and suppress reprint"
)

REFERENCE_RELEASE_PRESERVATION = (
    "preserve WND reference behavior for fulfillment, customer/A-R identity, financial truth, "
    "historical inventory evidence and kitchen semantic-delta output without promoting Track A "
    "implementation details into neutral Track B authority"
)
