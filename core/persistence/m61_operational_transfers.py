"""Frozen M6.1 persistence inventory."""

PARENT_REVISION = "m60_operational_balance_authority_016"
TARGET_REVISION = "m61_transfers_reconciliation_017"
TEST_DATABASE_NAME = "xbos_track_b_m61_transfers_test"
M61_VIEW = "operational_account_reconciliation_series"
M61_EVENT_TYPES = ("VALUE_TRANSFERRED", "FINANCIAL_FACT_REVERSED")
M61_ACCOUNT_ROLES = ("source_operational_asset", "target_operational_asset")
