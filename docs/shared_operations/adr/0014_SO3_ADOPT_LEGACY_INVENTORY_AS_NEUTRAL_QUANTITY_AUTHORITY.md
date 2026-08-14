# ADR 0014: Adopt legacy inventory as neutral quantity authority

Status: accepted for SO3.

The established inventory tables contain authoritative operational history and stable references. SO3 therefore enriches them in place and maps legacy branches through the PC1 compatibility table. It does not create a second stock ledger or rekey Atomic Units.

Positions are concurrency-controlled projections. Movements are append-only facts; corrections are compensating facts; transfers are paired and quantity-conserving. Reservations affect availability without inventing ownership or value. Financial valuation and posting remain outside SO3.
