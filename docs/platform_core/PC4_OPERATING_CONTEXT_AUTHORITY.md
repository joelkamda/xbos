# PC4 typed configuration and prospective operating context

PC4 establishes one canonical owner for typed, scoped, effective-dated generic business configuration. Each definition declares its type, owner, legal scopes, exact resolution order, validation, default semantics, secret status, and tenant override policy. Values use typed persistence columns; structured JSON is an explicit type, not the universal representation.

Secret material is forbidden. `secret_references` holds only opaque binding names that operators resolve outside ordinary configuration and exports.

The core-module registry is metadata and does not change `main:app`, startup ordering, router registration, middleware, ORM loading, or static imports. Module availability, tenant enablement, commercial entitlement, operational feature activation, and PC5 permission authorization remain independent decisions. PK retains pack manifests and lifecycle.

PC4 calendars and shifts resolve prospective generic operating time from an explicit UTC instant and IANA timezone. They preserve local wall time, calendar date, business date, shift, policy identity, and version. Neutral Finance retains all frozen resolved historical financial dates, windows, policy references, and close facts; PC4 never recalculates them.

Tenant localization and terminology are presentation context. PC3 semantic codes remain stable, Finance owns monetary currency, and SO7 owns referenced branding files.

Run `XBOS_PC4_RUN_ACCEPTANCE.cmd` from checkpoint `601a395` in the approved active environment. The gate rehearses `pc3_semantic_authority_023 -> pc4_operating_context_024` on a disposable `template0` database before controlled development adoption.
