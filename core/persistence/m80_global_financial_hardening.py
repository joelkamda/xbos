"""Persistence marker: M8.0 adds tests and no financial persistence authority."""

SCHEMA_NEUTRAL = True
WRITES_NEW_TABLES = False
CREATES_FINANCIAL_AUTHORITY = False
REROUTES_LEGACY_WRITERS = False
CUTOVER_AUTHORIZED = False
LIVE_CUTOVER_OWNER = "R6"
