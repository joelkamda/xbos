# M7.1 — WND source-to-canonical financial mapping

M7.1 turns immutable WND source snapshots into deterministic, ordered canonical command plans. Plans are descriptive: they do not execute commands, write database rows, import into legacy services, or alter production routes.

## Supported paths

- A commercial sale maps gross revenue recognition, governed discount/complimentary components, and an open receivable when customer value remains unpaid.
- A verified payment maps a canonical payment intent and incoming settlement. Payment changes assets and settlement clearing; it never recognizes revenue.
- A receivable repayment maps the same verified settlement followed by receivable allocation. It never recognizes revenue a second time.
- A refund maps an append-only `RecognizeRefundCommand` linked to original and refund settlement identities and immutable evidence. It does not edit original revenue.

The mapper derives stable UUIDs, idempotency identities, command ordering, source fingerprints, and plan fingerprints from tenant, organization, and source identity. Identical replay returns an identical plan; changed payload under the same source identity is detectable as an idempotency conflict.

## Finality and evidence

Raw provider success is not settlement authority. Non-cash settlement requires verified finality, a lowercase SHA-256 evidence hash, an external settlement reference, and a governed operational account. Offline cash is supported when its locally governed evidence is verified; no provider identity is invented.

## Boundaries

M7.1 does not own inventory/COGS or receipt linkage (M7.2), shadow execution and control totals (M7.3), dual reads and retirement readiness (M7.4), or final conformance (M7.5). R6 remains the sole owner of live WND operational cutover.
