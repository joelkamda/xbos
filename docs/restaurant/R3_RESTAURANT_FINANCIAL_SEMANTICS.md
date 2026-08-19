# R3 — Restaurant Financial Semantics

Source checkpoint: `c9ab012e8e666f2bf96b8ad50b571f608acfeebd`

Canonical database head remains: `r2_restaurant_menu_fulfillment_043`

Migration: `NONE`

R3 is a side-effect-free Restaurant-to-Neutral-Finance composition layer. It defines how Restaurant operational meaning becomes governed Finance command plans without creating a second ledger, payment authority, receivable system, or journal writer.

## Charges and modifiers

R1 order-to-obligation handoff remains operational evidence. R3 composes its base charge lines with the immutable R2 modifier selection snapshots. Positive modifier prices increase gross Restaurant commercial value; zero-price preparation choices remain operational only. R3 never re-prices SO1 catalog entries.

Gross commercial truth is mapped to `COMMERCIAL_REVENUE_RECOGNIZED`. Discounts and complimentary value remain reductions governed by M5.2; customer-facing service charges and output taxes remain additions governed by M5.2. Delivery/takeaway charges are not special ledgers: when customer-facing they are mapped as governed `customer_service_fee` components with a revenue-nature classification supplied by pack/tenant configuration. Provider fees remain provider-financial authority and are never disguised as customer fees.

The final customer obligation is only a Finance command descriptor. R3 never inserts an obligation. Walk-in/anonymous service therefore still requires an existing Party identity selected by tenant/platform configuration before an obligation can be handed to Finance.

## Tips and commissions

Tips map to the existing M5.3 tip policies (`staff_beneficiary` or `tenant_income`). Commissions map to M5.3 fixed/percentage commission semantics. Neither is treated as payment settlement. WND's staff rules, cut-off rules, and commission policy remain tenant/template configuration rather than Restaurant constants.

## Cancellations, voids, refunds, and reversals

Operational cancellation/void is allowed only before financial/external finality. Once canonical financial truth exists, R3 maps the required append-only correction or refund request into M5.4 semantics. Original recognized revenue is never edited or deleted by Restaurant.

## Reports

Restaurant report plans name Restaurant dimensions (for example service mode, source channel, waiter/cashier attribution) over Neutral Finance and SO9 read sources. R3 does not calculate or persist a parallel financial ledger.

## Database

R3 has no migration and creates no `r3_*` tables. The accepted database head remains R2 (`r2_restaurant_menu_fulfillment_043`).
