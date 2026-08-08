"""Static authority for the M3.0 obligation/allocation persistence gate."""

from __future__ import annotations


PARENT_REVISION = "m25_financial_dimensions_007"
TARGET_REVISION = "m30_obligation_foundation_008"
TEST_DATABASE_NAME = "xbos_track_b_m30_foundation_test"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"

FOUNDATION_TABLES = (
    "financial_obligations",
    "financial_obligation_lines",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
)

FROZEN_M2_COUNTS = {
    "financial_event_type_versions": 20,
    "financial_dimension_types": 0,
    "financial_dimension_values": 0,
    "posting_dimension_policies": 0,
    "idempotency_records": 0,
    "financial_events": 0,
    "outbox_messages": 0,
    "journal_entries": 0,
    "journal_lines": 0,
}


def expected_development_counts() -> dict[str, int]:
    """Return a fresh copy of the M2 and M3.0 empty-state acceptance counts."""

    return {
        **FROZEN_M2_COUNTS,
        **{table: 0 for table in FOUNDATION_TABLES},
    }
