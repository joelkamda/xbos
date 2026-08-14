# ADR 0021 — SO10 time/capacity booking is separate from workflow and Finance

## Decision

SO10 owns prospective time-bound availability, reservation state, Resource-capacity allocation and operational service execution. It consumes PC4 business time, SO1 schedulable targets, PC2/SO2 Party context and SO5 Resources through stable references.

## Boundaries

A calendar entry is not an SO6 task. A reservation is not a financial obligation. Confirming capacity does not grant PC5 permission. Completing service does not recognize revenue, create COGS, post a journal, create a payable/receivable or settle payment.

## Concurrency

Confirmation/rescheduling serialize the SO10 reservation and selected availability window, then lock referenced SO5 Resources in deterministic order. Capacity checks use current reservation-version allocations; older allocation rows remain immutable history.

## Compatibility

Legacy timestamps and domain-specific booking concepts remain source-owned until explicit bridges and later pack/R6 cutover prove replacement. No historical production data is bulk-reinterpreted in SO10.
