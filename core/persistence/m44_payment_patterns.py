"""Static M4.4 migration and acceptance inventory."""
PARENT_REVISION="m43_payment_settlements_013"
TARGET_REVISION="m44_payment_patterns_014"
TEST_DATABASE_NAME="xbos_track_b_m44_patterns_test"
M44_TABLES=("payment_tender_transitions",)
M44_TENDER_COLUMNS=("terminal_at","failure_code","evidence_payload")
M44_SETTLEMENT_COLUMNS=("payment_tender_id",)
M44_TRIGGERS=("trg_payment_tender_validate_insert","trg_payment_tender_initial_transition","trg_payment_tender_transition_validate","trg_payment_tender_transition_immutable","trg_payment_tender_guard_update","trg_payment_tender_reject_delete","trg_payment_pattern_settlement_validate","trg_payment_pattern_settlement_guard")
FORBIDDEN_SIDE_EFFECT_TABLES=("provider_callback_events","value_sources","payment_allocations","financial_events","outbox_messages","journal_entries","journal_lines")
