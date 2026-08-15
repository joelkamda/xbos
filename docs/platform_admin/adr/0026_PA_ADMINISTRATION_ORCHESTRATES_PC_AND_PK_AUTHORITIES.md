# ADR 0026 — Platform Administration orchestrates, it does not absorb Platform Core or Pack authority

**Decision:** PA may coordinate merchant lifecycle, commercial plans/subscriptions, usage/quota evidence and onboarding readiness, but canonical tenant lifecycle stays PC1, effective entitlements stay PC4, authorization/admin identity stays PC5, and template composition stays PK.

This prevents the admin console from becoming a second source of truth. PA records administrative/commercial facts and evidence, then consumes public authority results. It never treats a commercial subscription row as proof that a capability is currently authorized or enabled.
