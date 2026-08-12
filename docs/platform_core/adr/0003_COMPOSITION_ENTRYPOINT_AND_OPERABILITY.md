# ADR 0003: Composition, Entrypoint, and Dependency Operability

- Status: Accepted
- Scope: PC0

## Decision

`main:app` is the canonical deployment entrypoint. `app:app` is compatibility-only and remains byte-for-byte unchanged in PC0. The application factory, router assembly, middleware registration/effective ordering, ORM model registration, startup side effects, and composition files are fingerprinted as frozen evidence.

The repository's absent production dependency authority is an explicit operability gap. PC0 does not invent requirements or lock files. Platform Operations owns retirement of the gap at E5.

## Consequences

PC0 introduces governance contracts, a standard-library static validator, tests, documentation, and packaging only. It does not import application startup during static verification and changes no routing, middleware, startup, API, database, or migration behavior.
