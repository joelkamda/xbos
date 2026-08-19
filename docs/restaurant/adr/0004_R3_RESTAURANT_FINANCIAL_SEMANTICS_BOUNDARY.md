# ADR 0004 — R3 Restaurant financial-semantics boundary

## Decision

Restaurant owns the interpretation of Restaurant operational evidence for financial handoff, but Neutral Finance owns every canonical financial fact and writer. R3 is deterministic mapping-plan code only and therefore requires no database migration.

## Consequences

- R1/R2 operational evidence is preserved and referenced.
- Finance M2/M3/M5 contracts are consumed without invoking their engines/repositories.
- Discounts, complimentary value, service fees, taxes, tips, commissions, refunds, and reversals preserve their existing Finance distinctions.
- Restaurant reports are projections over Neutral Finance/SO9, never an alternate ledger.
- WND-specific finance rules remain tenant/template configuration.
