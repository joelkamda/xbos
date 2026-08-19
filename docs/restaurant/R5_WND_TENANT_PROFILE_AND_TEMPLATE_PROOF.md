# R5 — WND Tenant Profile and Restaurant Template Proof

Source checkpoint: `7b52093f6fcbe264a56bb1cf673c937488125a3f`
Accepted schema head: `r2_restaurant_menu_fulfillment_043`
Migration: **none**

## Purpose

R5 proves that the neutral Restaurant pack can be composed for Wine & Dine without making Wine & Dine the definition of Restaurant.

The proof is deliberately separated from production cutover. R5 uses a WND-shaped Track B proof tenant, `wnd-r5-proof`, with a canonical Logpom location. The live WND database `xbos` remains untouched. R6 owns the later production migration, frontend UAT, writer cutover and rollback proof.

## Restaurant templates

R5 registers two immutable PK template versions:

- `restaurant.counter_service@1.0.0`
- `restaurant.full_service@1.0.0`

Both require certified and active `industry.restaurant@1.0.0`.

WND is pinned to the counter-service template with explicit tenant overrides:

- enabled service modes: dine-in, takeaway and delivery;
- tips disabled;
- commissions enabled.

The sibling full-service template keeps tables, reservations and course firing enabled. That sibling is intentional evidence that WND's current lower-complexity operating model is not the Restaurant capability ceiling.

## WND structural proof

R5 provisions a proof-only canonical PC1 structure:

- tenant: Wine & Dine — Track B Proof;
- legal entity: Wine & Dine Cameroon;
- organization: Wine & Dine;
- location: Logpom;
- country: Cameroon;
- currency: XAF;
- timezone: Africa/Douala.

This tenant is not production WND and is not a cutover identity. R6 will map the actual WND production tenant and legacy branch only after explicit cutover authorization.

## 08:00–08:00 business day and 18:00 attribution

The WND business calendar is materialized through PC4, not hard-coded into the kernel or Restaurant runtime:

- business-day boundary: 08:00 Africa/Douala;
- day shift: 08:00–18:00;
- night shift: 18:00–08:00;
- payment-shift cutoff: 18:00.

The 18:00 cutoff changes payment/shift attribution only. Commission attribution remains the original order creator, preserving the accepted WND rule.

Acceptance explicitly proves 07:59, 08:00, 17:59 and 18:00 boundary behavior through the PC4 `BusinessTimeResolver`.

## Payment configuration

WND payment choices are tenant configuration:

- settlement: cash, MTN Mobile Money, Orange Money;
- composition: split and unpaid receivable;
- accounting channels: cash, MTN, Orange, XafPay, bank, A/R and A/P.

These values are not Restaurant-wide or kernel constants.

## Branding and terminology

WND branding and terminology are applied through the PC4 localization contract. The proof tenant uses the `Wine & Dine` display name and tenant-owned terminology such as Cashier, Kitchen, Waiter and Sales Archive. No binary asset or local file is embedded in the profile.

## Menu/catalog and staff mappings

R5 freezes the migration plan but does not move production data.

Legacy `atomic_units`, `taxonomy_nodes`, `atomic_unit_taxonomy` and `sale_items.atomic_unit_id` map to SO1 catalog truth plus R2 Restaurant menu projections during R6.

Legacy WND staff roles map to PC5 tenant roles/permissions and R1 operational waiter/cashier attribution. The exact role transformation remains explicit and provenance-bearing at R6.

## Taxonomy overlay

R5 does not copy the WND taxonomy into a second global taxonomy. The plan is:

1. reuse global/pack semantic identity where equivalent;
2. use PC3/SC41 tenant overlays for WND-specific labels, ordering, suppression or parent overrides;
3. classify SO-owned targets through governed SC41 target types;
4. preserve source IDs and provenance for R6 migration evidence.

No bulk rewrite occurs in R5.

## Finance, documents and inventory

R5 adds no Finance, SO1, SO3, SO7 or SO8 writer.

- Restaurant financial meaning remains R3 -> Neutral Finance.
- Kitchen/document delivery remains R2 -> SO7/SO8 handoff.
- Inventory remains SO3 authority.
- The fourteen accepted Track A invariants remain migration constraints.
- Historical WND costing is not generalized into a universal Restaurant costing model.

## Persistent development proof

Only after predecessor checks, R5 static/focused tests, disposable PostgreSQL proof, full regression, compilation/JSON/whitespace checks does the gate adopt R5 into `xbos_track_b_dev`.

Allowed persistent changes are composition data only:

- one WND-shaped proof tenant and Logpom structural context;
- the two immutable Restaurant template versions;
- active Restaurant pack lifecycle for the proof tenant;
- the proof tenant's template binding and explicit overrides;
- PC4 effective configuration, calendar and localization.

The Alembic head remains `r2_restaurant_menu_fulfillment_043`.

## R6 boundary

R5 does **not** authorize:

- production WND migration;
- production frontend cutover;
- legacy writer retirement;
- production Finance or inventory rerouting;
- historical bulk transformation.

Those belong to R6 and require explicit cutover approval.
