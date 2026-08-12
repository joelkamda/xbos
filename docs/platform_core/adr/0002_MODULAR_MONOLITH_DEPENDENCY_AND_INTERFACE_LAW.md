# ADR 0002: Modular-Monolith Dependency and Interface Law

- Status: Accepted
- Scope: PC0

## Decision

The module map defines ownership roots. Cross-module imports are default-deny and pass only through an allowed direction or one exact named legacy exception. Exception matching includes source path, imported name, source module, and target module; wildcard and path-prefix exceptions are forbidden.

Existing violations are baselined with rationale, retirement owner, and milestone. PC0 does not repair them. A matching dependency from a new source path is a new violation and fails. Each module declares public and private interfaces; declarations document compatibility surfaces and do not create new APIs, routers, writers, or runtime behavior.

## Consequences

The enforcement suite scans the actual startup/router/middleware/ORM/module composition and production source roots. It rejects unmapped internal production sources, prohibited new edges, baseline drift, interface inconsistency, incomplete ownership, and incomplete reference migration entries.
