# M3.6 — Hardening, Acceptance Baseline, and M3 Freeze

## Outcome

M3.6 closes the obligations, balances, and allocations milestone without adding
a migration or changing a writer. It freezes the approved M3.0–M3.5 contracts,
proves their single migration lineage, verifies the empty development target,
and runs all six disposable capability rehearsals through one fail-fast gate.

The canonical head remains `m34_obligation_aging_010`.

## Frozen capability set

- M3.0: obligation, value-source, and allocation persistence foundation.
- M3.1: typed obligation creation, lifecycle, and balance projections.
- M3.2: transactional allocation, capacity, policy, concurrency, and reversal.
- M3.3: deposits, unapplied value, later application, and overpayments.
- M3.4: deterministic current/as-of obligation aging and lifecycle history.
- M3.5: read-only obligation settlement trace and explanation.

The release manifest records semantic SHA-256 fingerprints for each approved
contract. Formatting changes do not alter these hashes; semantic changes do.

## Hardening of earlier verifiers

M3.0–M3.3 development guards originally accepted only the revision current
when each slice was introduced. M3.6 makes those guards descendant-aware along
the approved single lineage through M3.4. Their disposable rehearsal targets,
upgrade targets, downgrade proofs, and financial invariants remain unchanged.

This permits consolidated acceptance without weakening revision authority.

## Single fail-fast gate

The packaged runner checks:

1. the exact branch and starting commit;
2. JSON and Python syntax;
3. the single Alembic head and current development revision;
4. manifest semantics and empty development state;
5. absence of all six named disposable databases;
6. every M3.0–M3.5 disposable rehearsal, sequentially;
7. the complete regression suite and whitespace gate.

The first failure stops the run. Only then should segmented diagnosis begin.
Successful rehearsals drop every disposable database; a failing capability
retains only its guarded database for inspection.

## Freeze boundary

M3.6 adds no route, migration, WND writer, development financial fact, tenant
configuration, or outbox dispatch. After approval, the milestone is tagged
`track-b-m3-obligations-balances-allocations-20260809` and subsequent work
branches from that immutable checkpoint.
