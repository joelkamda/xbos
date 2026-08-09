"""Static M4.1 command-engine policy."""

TARGET_REVISION = "m40_payment_foundation_011"
TEST_DATABASE_NAME = "xbos_track_b_m41_payment_commands_test"

WRITTEN_TABLES = (
    "canonical_payment_requests",
    "canonical_payment_intents",
    "idempotency_records",
)

FORBIDDEN_SIDE_EFFECT_TABLES = (
    "canonical_payment_tenders",
    "canonical_payment_attempts",
    "provider_callback_events",
    "payment_settlements",
    "payment_settlement_reversals",
    "value_sources",
    "financial_events",
    "outbox_messages",
)
