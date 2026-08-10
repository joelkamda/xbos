"""M5.2 persistence marker: canonical source, event, outbox, and journal tables are reused."""

SCHEMA_NEUTRAL = True
CANONICAL_HEAD = "m46_provider_financials_015"
WRITES_NEW_TABLES = False
AUTHORITATIVE_TABLES = ("kernel_source_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines")
