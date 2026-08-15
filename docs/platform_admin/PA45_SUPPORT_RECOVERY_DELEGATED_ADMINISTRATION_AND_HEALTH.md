# PA45 — Support, Recovery, Delegated Administration and Health

PA45 covers Final Master WBS PA4 and PA5. It extends Platform Administration without changing PC, PK, Shared Operations or Finance authority.

## Authority boundary

PC5 remains the source of authorization and authenticated identity. A PA45 support session is a bounded administrative access envelope and evidence trail, not a role grant or a second permission system. PC1 remains tenant lifecycle authority. PA0123 remains merchant lifecycle/subscription/onboarding authority. PK remains pack/template composition authority.

## Support and delegated administration

Delegated support requires an explicit tenant, actor identity, scope set, reason, start/expiry, authorization reference and PC5 authorization evidence. Break-glass access is stricter: maximum one hour, step-up reference and incident/break-glass evidence are mandatory. Support actions are append-only evidence records. Closing or revoking a session does not erase its history.

## Recovery

Recovery cases record the administrative problem, subject reference, evidence and immutable recovery actions. A recovery action may be associated with an active support session, but the case never silently mutates the authority being diagnosed. Repairs must continue through the affected module's public contract.

## Merchant and platform health

Health snapshots are derived evidence. Each check carries status, evidence reference and observation time. Overall status uses the worst observed status: healthy < unknown < degraded < blocked. A health result can inform operators but cannot authorize mutation, settlement, posting, pack changes or tenant lifecycle changes.

## Security and privacy

Generic support/recovery metadata rejects secret-like fields. Credentials, access tokens and raw secrets belong in dedicated secret authorities, never Finance events, health snapshots or generic audit metadata.

## Migration

`pa0123_merchant_lifecycle_subscriptions_onboarding_039 -> pa45_support_recovery_health_040`

The migration is additive and creates PA-owned support, recovery and health evidence tables. Existing Finance and Shared Operations tables are untouched.
