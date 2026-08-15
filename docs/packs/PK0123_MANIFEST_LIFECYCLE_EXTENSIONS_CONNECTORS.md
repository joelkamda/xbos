# PK0123 — Pack Manifest, Lifecycle, Public Extensions and Connector Declarations

PK0123 establishes the first executable Pack Platform layer. A pack is composition, never a new authority for Finance, Party, semantics, configuration, authorization, inventory, workflow, settlement or reconciliation.

## Scope

PK0 defines immutable machine-readable pack/version manifests and dependency declarations. PK1 defines tenant lifecycle with staged, installed, active, disabled and retention-aware removed states. PK2 permits extensions only through named public authority contracts. PK3 introduces typed country/tax/provider/accounting/communication/integration declarations without runtime dynamic imports or arbitrary SQL.

## Authority reuse

PC3 remains semantic identity/taxonomy authority. PC4 remains module, entitlement, feature and typed configuration authority. PC5 remains authorization and permission authority. SO1-SO10 retain operational truth. Neutral Finance remains financial truth and M8.4 remains the pack financial-conformance authority. XA remains the frontend experience contract.

Pack activation does not itself grant entitlement, flip a feature flag, enable a PC4 module or grant a PC5 permission. Those effects require their own public-authority commands during later application/orchestration stages.

## Provider connector boundary

Provider execution evidence is not settlement truth. Connector declarations distinguish submitted, pending, failed, ambiguous and provider-final evidence. Unknown payout outcomes are never blindly retried. Stable XBOS instruction identity, provider submission idempotency/external reference and callback/event identity are separate concerns. Provider destination/routing data remains adapter detail and sensitive values are referenced rather than copied into Finance events or journals.

PK0123 does not create an outbound PaymentIntent, PaymentAttempt or provider payout ledger. Reopening Finance remains deferred unless an implementation/conformance test proves a universal financial invariant cannot be represented truthfully using frozen canonical authorities.
