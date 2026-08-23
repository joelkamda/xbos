# ADR 0010 — WND production cutover precedes legacy-writer retirement

## Decision

R6.5 will move WND production onto the neutral schema and R6.4-frozen Track B
runtime while retaining the accepted legacy WND writer routing and the R6.3
compatibility bridge during hypercare.

Legacy writer retirement is a separate post-hypercare decision.

## Why

R6.3 proved the frozen WND application can operate correctly on the neutral
`r63` schema, including order placement, settlement, fulfillment modes,
Cashier/Kitchen, exact-once inventory, A/R and reporting. That compatibility
creates a safer production transition than coupling schema adoption and writer
retirement into one irreversible event.

It also creates a post-reopen rollback path that preserves new business
transactions: the application can return to the frozen Track A backend against
the neutral schema without restoring an old database backup.

## Consequences

- R6.4 and R6.5 do not retire legacy writers.
- Neutral schema presence does not imply canonical financial-writer authority.
- Hypercare produces the evidence required for a later retirement plan.
- After the first post-cutover business write, blind database restore is
  forbidden.
- WND remains the migration proof; fresh WND onboarding after F-track becomes
  the administration/template proof; Olympia becomes the repeatable second
  Restaurant-tenant proof.
