# ADR 0009 — Exact WND release source is the R6.3 compatibility oracle

## Decision

R6.3 tests the exact committed Track A reference backend and frontend source
against a disposable neutralized candidate. It does not port WND UI/API code
into neutral kernel authority merely to make the compatibility gate green.

Visual acceptance remains an explicit human gate. Automated tests may prove
build, startup, OpenAPI, route compatibility and data-control preservation but
must not manufacture a visual-UAT PASS.

## Consequences

- WND remains a production specimen, not the Restaurant capability ceiling.
- Track B neutral authorities remain separate from WND presentation/source.
- Candidate-only startup writes such as legacy RBAC seed compatibility are
  permitted only inside the disposable R6.3 candidate and may not change the
  frozen business controls or public schema.
- Production `xbos`, production port 8001 and production frontend port 5173
  remain outside R6.3 write/runtime authority.


## UAT compatibility migration

The exact-release oracle exposed a schema/writer coexistence defect in SO3:
legacy Track A inventory INSERTs do not supply SO3-required neutral columns.
The correction belongs on the neutral schema boundary, not in the frozen WND
application. R6.3 therefore adds a temporary compatibility adapter migration
that derives neutral location/time/reason provenance while legacy writers are
still active. R6.4/R6.5 may retire this bridge only together with the actual
writer-authority transition.
