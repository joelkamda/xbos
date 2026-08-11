"""Frozen M6.2 persistence inventory."""

PARENT_REVISION = "m61_transfers_reconciliation_017"
TARGET_REVISION = "m62_reconciliation_windows_018"
TEST_DATABASE_NAME = "xbos_track_b_m62_reconciliation_test"
M62_TABLES = (
    "reconciliation_calendar_policies",
    "reconciliation_series",
    "reconciliation_windows",
    "reconciliation_cascade_runs",
    "reconciliation_window_revisions",
)
M62_CURRENT_VIEW = "current_reconciliation_window_revisions"
