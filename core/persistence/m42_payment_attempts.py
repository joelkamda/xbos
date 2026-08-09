"""Static migration and verification policy for M4.2 payment attempts."""

PARENT_REVISION = "m40_payment_foundation_011"
TARGET_REVISION = "m42_payment_attempts_012"
TEST_DATABASE_NAME = "xbos_track_b_m42_attempts_test"

M42_TABLES = ("canonical_payment_attempt_transitions",)
M42_COLUMNS = (
    "retry_of_attempt_id",
    "timeout_at",
    "terminal_at",
    "failure_code",
)
M42_TRIGGERS = (
    "trg_payment_attempt_validate_insert",
    "trg_payment_attempt_initial_transition",
    "trg_payment_attempt_transition_validate",
    "trg_payment_attempt_transition_immutable",
    "trg_payment_attempt_history_consistent",
    "trg_payment_attempt_guard_update",
    "trg_payment_attempt_reject_delete",
)
FORBIDDEN_SIDE_EFFECT_TABLES = (
    "canonical_payment_tenders",
    "provider_callback_events",
    "payment_settlements",
    "payment_settlement_reversals",
    "value_sources",
    "financial_events",
    "outbox_messages",
)
