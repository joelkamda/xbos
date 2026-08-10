"""Frozen M6.0 persistence inventory."""

PARENT_REVISION = "m46_provider_financials_015"
TARGET_REVISION = "m60_operational_balance_authority_016"
TEST_DATABASE_NAME = "xbos_track_b_m60_balance_test"
M60_TABLES = (
    "operational_account_authorities",
    "operational_account_balance_anchors",
    "operational_account_balance_observations",
)
M60_PROVENANCE = (
    "opening_import",
    "operator_confirmed",
    "external_confirmed",
    "operator_counted",
    "external_statement",
    "provider_confirmed",
)
