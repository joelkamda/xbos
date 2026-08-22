# R6.3 — WND application compatibility and visual UAT

R6.1 proved structural adoption of the real WND production snapshot. R6.2
proved that production-shaped financial/operational truth can be mapped or
explicitly withheld without fabrication. R6.3 tests the accepted WND reference
application itself against the neutralized candidate.

## Authority boundary

R6.3 does not switch any live writer. Visual UAT exposed one backward-compatibility gap introduced by SO3: the still-active Track A inventory ORM does not populate SO3's new required neutral columns on INSERT. R6.3 therefore adds a narrowly-scoped compatibility migration at `r63_legacy_inventory_writer_compat_044`. Production `xbos`
is not a rehearsal target. The only database targets are disposable
`xbos_r6_3_source` and `xbos_r6_3_candidate`.

The application under test is not reconstructed from memory. R6.3 consumes the
exact frozen Track A backend `b60a71d...` and frontend `f47f574...`, both bound
to `wnd-track-a-reference-release-20260821`.

## Automated compatibility

The automated gate restores the immutable 21 Aug backup, repeats the proven
neutral adoption/composition, starts the exact Track A backend against the
candidate, generates its OpenAPI schema, exercises representative authenticated
read routes, and requires no public-schema, legacy-count, financial-control or
reference-schema drift from application startup/read activity.

The exact Track A frontend is source-checked and rebuilt. Its original Vite
configuration is not edited. A UAT-only configuration is generated in the
Downloads workspace so `/api` proxies to candidate backend port 8002 rather
than production port 8001.

## Visual UAT

Automated compatibility cannot prove visual acceptance. The operator runs the
exact frozen frontend on port 5174 against the exact frozen backend on port
8002/candidate DB and checks the frozen UAT matrix. Explicit operator
acceptance is recorded as evidence. No visual PASS is inferred from build,
OpenAPI or route-smoke success.

## Exit

R6.3 PASS means the accepted WND reference application is compatible with and
visually accepted against the neutralized production-shaped candidate. It does
not authorize production cutover. R6.4 owns the deterministic final production
cutover package and runbook.


## UAT-discovered legacy inventory writer bridge

The exact Track A WND application proved that generic reads and manual
Accounting/Treasury writes remained compatible, while order placement and
order-linked settlement failed. Both failing paths cross the legacy inventory
reservation/finalization writer.

SO3 had made `inventory_movements.stock_location_id`, `occurred_at`, and
`reason_code` required, and `inventory_items.stock_location_id` required,
without a compatibility path for the frozen legacy ORM that does not know those
columns.

R6.3.5 fixes only that coexistence boundary. BEFORE INSERT adapters derive the
required neutral fields from already-authoritative SO3 mappings and legacy
movement identity. Quantity deltas, reservation/commit semantics, historical
evidence, financial authority, and writer routing are unchanged. Missing
location mappings fail closed.
