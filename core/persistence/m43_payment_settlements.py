"""Static migration and verification policy for M4.3 settlements."""

PARENT_REVISION = "m42_payment_attempts_012"
TARGET_REVISION = "m43_payment_settlements_013"
TEST_DATABASE_NAME = "xbos_track_b_m43_settlements_test"

M43_TABLES = ("payment_settlement_transitions",)
M43_COLUMNS = ("value_date", "terminal_at", "failure_code", "evidence_payload", "reversed_amount")
M43_TRIGGERS = (
    "trg_payment_settlement_validate_insert",
    "trg_payment_settlement_initial_transition",
    "trg_payment_settlement_transition_validate",
    "trg_payment_settlement_transition_immutable",
    "trg_payment_settlement_guard_update",
    "trg_payment_settlement_reject_delete",
    "trg_payment_settlement_reversal_validate",
    "trg_payment_settlement_reversal_apply",
)
FORBIDDEN_SIDE_EFFECT_TABLES = (
    "canonical_payment_tenders", "provider_callback_events", "value_sources",
    "payment_allocations", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
)
