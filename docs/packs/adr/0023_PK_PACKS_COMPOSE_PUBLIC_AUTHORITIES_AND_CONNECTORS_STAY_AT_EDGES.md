# ADR 0023 — Packs compose public authorities; connectors stay at the edges

## Decision

XBOS packs are immutable versioned declarations plus governed tenant lifecycle. They may reference public contracts and declare composition intent, but may not redefine or privately mutate another authority.

Provider connectors are typed edge declarations. Provider-specific destination, retry, finality and credential-reference semantics do not migrate into Neutral Finance merely for symmetry.

## Consequences

* Manifest versions are immutable and tenant installations are version-pinned.
* No arbitrary SQL or runtime dynamic Python import is accepted from a pack manifest.
* Pack activation never grants authorization by itself.
* Provider-final evidence is distinct from submitted or merely successful-looking provider states.
* Ambiguous payout outcomes are held/recovered, never guessed or blindly resubmitted.
* Finance remains frozen and M8.4 conformance is consumed rather than replaced.
