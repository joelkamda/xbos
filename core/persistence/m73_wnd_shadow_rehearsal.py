"""M7.3 is isolated rehearsal support and creates no canonical schema authority."""

SCHEMA_NEUTRAL = True
PRODUCTION_WRITES_ALLOWED = False
REROUTES_LEGACY_WRITERS = False
PERFORMS_LIVE_CUTOVER = False
EXECUTION_ENVIRONMENT = "isolated_disposable"
LIVE_CUTOVER_OWNER = "R6"
