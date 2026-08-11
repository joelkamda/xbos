# M7.4 — Dual-read, cutover readiness, and writer-retirement support

M7.4 supplies the evidence and planning controls needed for R6 to make a later
production-cutover decision. It does not perform that decision.

Dual-read compatibility pairs a legacy projection with its canonical shadow
projection at exactly the same tenant, organization, subject, currency, and
as-of boundary. Exact control totals are compared deterministically. Variances
remain visible; the compatibility layer never forces either authority to agree
and never silently falls back or changes read routing.

Financial-cutover readiness requires the complete evidence set covering the
legacy-authority inventory, mapping coverage, shadow rehearsal, control-total
parity, tenant isolation, replay/conflict behavior, recovery, dual-read
compatibility, and a rollback runbook. A passing assessment means only
`ready_for_r6_review`; it cannot authorize cutover.

Writer-retirement support derives candidates from the accepted M7.0 inventory.
Every candidate retains its current legacy route, canonical targets, and an
explicit rollback reference. Plans are reversible and non-executing. Failed
readiness blocks every candidate.

M7.4 is schema-neutral. It does not switch financial authority, reroute or
disable a legacy writer, alter WND production, or perform operational cutover.
R6 owns those actions. M7.5 owns aggregate M7 conformance and freeze.
