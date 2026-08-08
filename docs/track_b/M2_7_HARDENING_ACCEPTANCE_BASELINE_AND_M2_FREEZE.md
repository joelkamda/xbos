# M2.7 — Hardening, Acceptance Baseline, and M2 Freeze

## Decision

M2.7 closes the canonical financial-event-engine milestone by freezing the
approved semantic contracts, migration lineage, empty development-state
invariants, and executable acceptance evidence delivered through M2.6.

This slice adds no database migration and writes no financial data. The
canonical Alembic head remains `m25_financial_dimensions_007`.

## What is accepted

The M2 release candidate contains:

- the M0 neutral financial vocabulary, entity, lifecycle, reliability,
  workflow, event-catalog, account-role, and posting-scenario contracts;
- the M1 canonical persistence authority, clean-room reconstruction baseline,
  and neutral financial schema foundation;
- the M2.0 canonical event-type catalog seed;
- the M2.1 typed immutable event engine;
- the M2.2 transactional idempotency and outbox boundary;
- the M2.3 original-linked correction and reversal-capacity guard;
- the M2.4 canonical balanced-posting engine;
- the M2.5 tenant-defined financial dimensions and posting context; and
- the M2.6 deterministic, tenant-scoped, read-only financial trace service.

## Frozen acceptance invariants

The release is accepted only while all of the following remain true:

1. Canonical JSON contracts retain their approved semantic SHA-256 values.
2. The canonical migration lineage is one linear chain ending at
   `m25_financial_dimensions_007`.
3. Financial events, posted journals, journal lines, and dimension snapshots
   remain immutable facts.
4. Command idempotency is tenant-scoped, replay-safe, and conflict-detecting.
5. Corrections point to an original event, match its correction semantics, and
   cannot exceed its remaining capacity, including under concurrency.
6. Every posted journal is balanced and bound to canonical account roles.
7. Required, forbidden, defaulted, overridden, tenant-scoped, and inherited
   dimensions obey the M2.5 policy.
8. Financial traces are deterministic, tenant-scoped, and read-only.
9. The development database remains an empty canonical target: 20 catalog
   rows and zero idempotency, event, outbox, journal, and dimension rows.
10. No M2 implementation imports FastAPI routes or legacy WND financial
    writer modules.

## Release manifest

`contracts/finance/v1/m2_release_manifest.json` records the semantic digest of
each accepted contract. Digests are calculated from parsed JSON serialized
with sorted keys and compact separators. Formatting-only edits therefore do
not invalidate the release, while semantic changes do.

This deliberately freezes behavior and authority rather than Python source
bytes. Compatible repairs may still be made, but a contract, lineage, or
boundary change requires an explicit later milestone and new acceptance
evidence.

## Executable acceptance

`scripts/verify_m27_m2_acceptance.py` provides three commands:

- `status` confirms that all seven named M2.0–M2.6 disposable databases are
  absent;
- `verify` validates the release manifest, static architectural boundaries,
  canonical migration lineage, development revision, and empty development
  counts; and
- `create-and-verify` runs the M2.0–M2.6 disposable database rehearsals, checks
  their explicit PASS evidence, confirms each database was dropped, and then
  rechecks the release manifest and development database.

The verifier fails closed when a disposable database already exists. A failed
child rehearsal retains only its named disposable database for inspection; use
that child verifier's exact guarded drop command after diagnosing the failure.

Historical capability rehearsals run from immutable Git checkpoint archives.
Each archive contains the code and migration head that were approved together,
while the aggregate runner supplies the configured local database URL. This
prevents both moving-head drift and attempts to run current code against an
older incompatible schema, and keeps the aggregate reproducible after later
canonical migrations are added.

## Explicit boundary

M2.7 does not authorize WND writer cutover. It also does not authorize public
financial routes, outbox dispatch, tenant dimension seeding, industry-pack
activation, development financial-event creation, or a new schema migration.

Those are later, separately gated changes. The recommended next phase is M3:
controlled writer integration and shadow/parity operation against the frozen M2
kernel, followed by an independently approved cutover.

## Source-control release gate

After every acceptance gate passes:

1. commit the six M2.7 implementation files;
2. push the clean branch;
3. verify that `track-b-m2-canonical-event-engine-20260808` is absent locally
   and remotely;
4. create an annotated tag with message
   `Track B M2 approved canonical financial event engine`;
5. push that exact tag; and
6. verify the remote tag and a clean synchronized branch.

The tag is the immutable M2 handoff point. M3 should branch from that tag.
