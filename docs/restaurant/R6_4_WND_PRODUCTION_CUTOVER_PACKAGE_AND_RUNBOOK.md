# R6.4 — WND production cutover package and runbook

R6.4 is the final **planning and rehearsal** milestone before WND production
cutover. It performs no live schema migration, production writer switch, or
legacy-writer retirement.

## What R6.4 proves

R6.4 captures a fresh read-only planning backup from the still-running WND
production database and restores that exact backup into disposable R6.4
source/candidate databases. The candidate is then replayed through the already
accepted neutral lineage to `r63_legacy_inventory_writer_compat_044`.

The fresh rehearsal requires:

- the live production database still begins at legacy head `5c706797029a`;
- the fresh custom-format planning backup passes `pg_restore --list`;
- legacy row counts and financial/inventory/reconciliation controls remain
  unchanged by neutral schema adoption;
- existing WND Restaurant pack/template/PC4 composition remains deterministic;
- destroy/restore/replay produces the same cutover fingerprint;
- the exact accepted Track A backend still works on the fresh neutral candidate;
- the R6.4 Track B backend runtime exposes the frozen WND API contract and
  read behavior on that same candidate;
- the R6.3 legacy inventory-writer compatibility bridge works from both runtime
  source trees and rolls back its diagnostic probe.

The planning backup is **not** the R6.5 rollback backup. WND remains live while
R6.4 captures it. R6.5 must take a new final backup only after application
writers are stopped in the approved maintenance window.

## R6.5 cutover mode

The approved R6.5 mode is:

`neutral_schema_and_track_b_runtime_with_legacy_writer_compatibility`

This is deliberate. The user-approved sequence is WND production cutover,
hypercare, and only then legacy retirement. Therefore R6.5 installs the neutral
schema/platform/Restaurant composition and Track B runtime in production while
retaining the frozen legacy writer inventory and R6.3 compatibility bridge.

R6.5 does **not** treat schema presence as permission to switch financial or
inventory authority.

## Rollback

Before reopening WND, the final stopped-production backup is a complete rollback
anchor.

After reopening but before the first business write, full restore remains
possible only after re-entering maintenance and proving no post-cutover write.

After the first post-cutover business write, a blind restore is forbidden
because it would discard live transactions. The validated application rollback
is the exact Track A backend `b60a71d...` running against the retained neutral
`r63` schema; R6.3 already proved that compatibility path. The live database is
preserved for incident recovery.

## Hypercare and retirement

Hypercare is evidence-gated rather than calendar-only. Retirement requires at
least seven consecutive clean closed business windows, payment/A-R/reconciliation
truth, exact-once inventory, kitchen/cashier behavior, backup/restore and restart
proof, controlled writer-route evidence, and a meaningful accounting/reporting
close cycle. A 2–4 week observation period is a planning target, not a substitute
for evidence.

After retirement and the F-track, a fresh isolated WND tenant is provisioned
through official XBOS administration/templates as the operator-mastery proof.
Only then is Olympia Lounge & Restaurant onboarded with the same tools.
