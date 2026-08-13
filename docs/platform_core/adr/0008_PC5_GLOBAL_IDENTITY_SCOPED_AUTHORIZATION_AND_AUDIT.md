# ADR 0008 — Global Identity, scoped authorization, and append-only audit

Status: Accepted for PC5.

Global Identity is the authentication principal. Tenant membership is an effective-dated relationship and never a permission. Party remains the PC2 business-relationship authority. Platform and tenant assignments are different typed scopes; PC1 owns structural objects and PC5 stores only typed references.

Permissions use stable namespaced codes. Roles bundle permissions, assignments provide scope, constrained policy adds assurance/approval controls, and all ambiguity denies. Approval is limited to authorization of protected actions; SO6 retains generalized workflow.

JWT remains a compatible token mechanism, but cryptographic validity cannot override canonical session or membership revocation. Step-up is an expiring, revocable grant and does not permanently modify Identity.

Platform support and break-glass authority requires an explicit time-bound `support_access_grants` record tied to one permission, tenant, typed scope, approval, reason, and real operator identity. No special tenant or invisible impersonation path exists.

Generic audit evidence is append-only and safe-metadata only. Neutral Finance retains economic truth, SO9 delivery, SO7 documents, and PK pack lifecycle.
