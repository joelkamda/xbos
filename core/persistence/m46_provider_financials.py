"""Frozen M4.6 persistence inventory."""
PARENT_REVISION = "m44_payment_patterns_014"
TARGET_REVISION = "m46_provider_financials_015"
TEST_DATABASE_NAME = "xbos_track_b_m46_provider_test"
M46_TABLES = ("provider_settlement_components",)
M46_TRIGGERS = (
    "trg_provider_settlement_component_validate",
    "trg_provider_settlement_component_immutable",
)
M46_COMPONENT_TYPES = (
    "provider_fee",
    "reserve_hold",
    "reserve_release",
    "chargeback_loss",
)
