# M4.4 — Supported payment patterns and split tender

M4.4 activates the canonical tender structure installed in M4.0. It composes cash, mobile-money, bank, card, standalone, payment-request/link, mixed-tender and delayed-settlement patterns without embedding a provider adapter.

An intent defines allowed methods, whether mixed tender is permitted, and a maximum tender count. Tenders divide the exact intent capacity into explicit method-bound amounts. Attempts and settlements are then bound to the relevant tender, preventing a provider result from being applied to another split component.

Cash may settle without an external attempt. Mobile-money, bank and card settlements retain successful-attempt authority. Delayed settlement keeps occurrence, value date and recorded date distinct under M4.3.

Database triggers independently enforce method policy, contiguous tender numbering, maximum tender count, cumulative amount capacity, tender-bound mixed attempts, tender-bound settlement capacity, immutable amounts and append-only lifecycle evidence. Application commands add typed validation, idempotent replay and tenant-scoped repository access.

M4.4 does not add XafPay callbacks, signatures, gateway requests, provider retries, provider fees or reserves. Those remain M4.5 and M4.6 concerns.
