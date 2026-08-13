# ADR 0007: Typed configuration, module context, and prospective time

Status: accepted for PC4 operator rehearsal.

PC4 uses named typed definitions and typed value columns with definition-specific scope resolution. Tenant JSON and environment readers remain explicit compatibility sources until per-key adoption; they are not co-equal canonical writers. Secrets are references only.

The module registry describes installed core modules and dependencies without dynamic loading. Availability, enablement, entitlement, feature activation, and authorization are separate. PC5 owns authorization; PK owns pack lifecycle.

Generic business calendars and shifts are effective-dated prospective policy. Resolution uses aware instants and IANA zones, including overnight and DST behavior. Frozen Finance continues to own persisted historical financial time facts. No PC4 operation rewrites or derives those facts retrospectively.
