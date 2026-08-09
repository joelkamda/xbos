"""Static inventory for the M4.0 neutral payment foundation."""

TARGET_REVISION = "m40_payment_foundation_011"
PARENT_REVISION = "m34_obligation_aging_010"
TEST_DATABASE_NAME = "xbos_track_b_m40_payment_foundation_test"

FOUNDATION_TABLES = (
    "canonical_payment_requests",
    "canonical_payment_intents",
    "canonical_payment_tenders",
    "canonical_payment_attempts",
    "provider_callback_events",
    "payment_settlements",
    "payment_settlement_reversals",
)

LEGACY_COEXISTENCE_TABLES = (
    "payments",
    "payment_intents",
    "payment_attempts",
)

FROZEN_EMPTY_TABLES = (
    "idempotency_records",
    "financial_events",
    "outbox_messages",
    "journal_entries",
    "journal_lines",
    "financial_obligations",
    "financial_obligation_lines",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
    "allocation_scope_policies",
    "obligation_state_transitions",
)
