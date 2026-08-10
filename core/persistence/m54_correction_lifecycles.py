"""M5.4 marker: correction workflows reuse frozen event, settlement, obligation, and provider tables."""

SCHEMA_NEUTRAL = True
CANONICAL_HEAD = "m46_provider_financials_015"
WRITES_NEW_TABLES = False
AUTHORITATIVE_TABLES = ("kernel_source_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines", "financial_obligations", "payment_settlements", "provider_settlement_components")
