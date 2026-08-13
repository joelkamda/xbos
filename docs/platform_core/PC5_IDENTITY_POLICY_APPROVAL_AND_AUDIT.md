# PC5 — Identity, authorization, approval, and audit authority

PC5 installs one canonical security authority over global authentication Identity, tenant membership, revocable sessions, namespaced permissions, scoped authorization roles, constrained policy, security approval, segregation, step-up assurance, service/device principals, and append-only audit evidence.

Identity is not Party, tenant, staff, PartyRole, or authorization Role. Existing `users`, password verification, JWT, role JSON, permission levels, role packs, middleware, and decorators remain explicit compatibility mechanisms. PC5 does not silently migrate users or seed tenant-specific security data.

Authorization denies by default. Membership establishes participation only. Platform scope is never encoded as a special tenant. Structural scopes reference PC1 authority by both type and identifier. PC4 module availability, enablement, entitlement, and feature state remain independent prerequisites rather than permissions.

Delegated administration, merchant support, and break-glass access never use an invisible super-user bypass. A grant is explicit, permission-specific, tenant/scope-bound, approved, reasoned, revocable, limited to eight hours, and attributable in audit to the real platform operator.

Audit evidence records who/what/when/how/why and references financial records without duplicating economic truth. Accepted evidence is append-only, secret-safe, tenant isolated, and permission queried. PC5 creates no outbox, workflow engine, document store, or delivery system.

Migration: `pc4_operating_context_024 -> pc5_identity_policy_audit_025`.

## Cumulative release integrity

Platform Core text artifacts use `sha256_canonical_source_v1`: only Git-equivalent
`CRLF` line endings are converted to `LF` before SHA-256. No trimming, whitespace
collapse, JSON reserialization, or content normalization is permitted. Declared
binary artifacts are hashed as exact bytes. When Git metadata is available, a
tracked clean file is read from its committed blob; a dirty or untracked file is
hashed from the working tree so real mutations cannot be hidden. Source archives
use the same explicit text/binary classification and line-ending rule.

Historical PC1-PC4 hashes remain immutable. Each historical verifier resolves the
validated sequential release chain and requires an exact PC5 replacement proof for
every canonical mismatch; unknown, non-sequential, wildcard, missing, or surplus
replacement claims fail closed.
