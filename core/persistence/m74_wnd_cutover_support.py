"""M7.4 is advisory cutover support and creates no schema or routing authority."""

SCHEMA_NEUTRAL = True
DUAL_READ_MODE = "legacy_primary_canonical_shadow"
CUTOVER_AUTHORIZED = False
RETIREMENT_EXECUTION_ALLOWED = False
REROUTES_LEGACY_WRITERS = False
DISABLES_LEGACY_WRITERS = False
LIVE_CUTOVER_OWNER = "R6"
