# ADR 0003: Composition, Entrypoint, and Dependency Operability

- Status: Accepted
- Scope: PC0

## Decision

`main:app` is the canonical deployment entrypoint. `app:app` is compatibility-only and remains byte-for-byte unchanged in PC0. The application factory, router assembly, middleware registration/effective ordering, ORM model registration, startup side effects, and composition files are fingerprinted as frozen evidence.

PC0 originally recorded the absent production dependency authority as an operability gap. PC6 closes that gap under explicit control-room authorization with the exact-pinned `requirements-prod.txt` baseline derived from the accepted Python 3.13.3 environment. `requirements-test.txt` stays separate; Platform Operations owns later maintenance and approved upgrades at E5.

## Consequences

PC0 introduces governance contracts, a standard-library static validator, tests, documentation, and packaging only. It does not import application startup during static verification and changes no routing, middleware, startup, API, database, or migration behavior.
