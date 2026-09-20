# XGI2 Tenant Identity and Currency Foundation

Authority: `XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION`

Parent: `XBOS-XGI2-R4C-TENANT2-FOUNDATION-DESIGN`

Source parent: `c79d81094f8ee236851ae999582a453ecca63ec1`

## Scope

R4D materializes only the additive PC1 source needed to establish a governed stable WND tenant identity and the generic XAF currency foundation in a later database gate.

R4D does not create staging rows, modify schema, mutate the Finance kernel, create Render services, bind secrets, execute providers, or change Gateway state.

Existing PC1 files remain unchanged:

- `core/platform/structure/contracts.py`
- `core/platform/structure/service.py`
- `core/platform/structure/sql_repository.py`

## Stable WND tenant identity

The governed import identity is:

- tenant id: `2`
- code: `wnd`
- name: `Wine & Dine`
- lifecycle: `active`
- country: `CM`
- currency: `XAF`
- locale: `fr-CM`
- timezone: `Africa/Douala`
- legal entity: `WND-CM / Wine & Dine Cameroon`
- root organization: `WND / Wine & Dine`
- physical location: `LOGPOM / Logpom`

The command key is `pc1:tenant-identity-import:2:wnd:v1`.

The import reuses `ProvisionTenant` as the structural field contract and uses the existing `tenant_provisioning_commands` table for command-key replay, canonical request fingerprint, tenant binding, result context, and completion evidence.

The operation is fail-closed for:

- same command key with changed payload;
- occupied tenant id;
- occupied tenant code;
- matching tenant identity without governed import evidence;
- incomplete prior command evidence.

## Sequence law

The tenant table is transaction-locked against concurrent ordinary tenant insertion while the explicit stable identity is materialized.

Tenant id 2 is inserted explicitly. The sequence is never used to manufacture id 2 and is never decreased.

After the insert, the owned tenant-id sequence is advanced only when its current value is below the maximum existing tenant id. This prevents the next normal PC1 provisioning operation from colliding with the explicitly imported stable identity.

## XAF currency asset

The generic currency master-data command is `pc1:currency-asset:XAF:v1`.

Canonical values:

- code: `XAF`
- asset kind: `fiat`
- display name: `Central African CFA franc`
- minor unit scale: `0`
- maximum storage scale: `8`
- active: `true`

Replay evidence is carried in the existing `currency_assets.metadata` object. A matching semantic row with matching fingerprint is idempotent. Any semantic or fingerprint mismatch fails closed.

## Tenant XAF policy

The command key is `pc1:tenant-currency-policy:2:XAF:1`.

Canonical values:

- tenant: `2`
- currency: `XAF`
- rounding mode: `half_even`
- cash rounding increment: `0`
- policy version: `1`
- effective from: `2026-09-19T00:00:00Z`
- effective to: `NULL`
- active: `true`

The existing `kernel_source_records` table carries the governed source identity and request fingerprint for the policy. Matching replay is idempotent. Changed payload or partial evidence fails closed.

A second active effective policy may not overlap the existing policy window.

## Authority separation

This extension is structural/foundation authority only.

It does not:

- alter canonical Finance event semantics;
- write payment settlements;
- construct journal entries;
- create operational financial accounts;
- create payment intents or attempts;
- create tenant 2 in R4D;
- create XAF rows in R4D.

Those runtime effects remain for later separately authorized gates.

## Future accepted staging composition

R4C froze the later staging composition as:

- XafPay operational account class: `treasury`
- XafPay operational account type: `gateway`
- account code: `xafpay-clearing`
- first signed event: `payment.created`
- first signed event financial effect: zero
- Render Python runtime: `3.13.3`

R4D records those future constraints but does not materialize them.

## Acceptance

Offline acceptance must prove:

1. the exact 11-path R4D envelope;
2. no historical PC1 source rewrite;
3. no Finance-kernel source mutation;
4. no Alembic/schema mutation;
5. deterministic tenant and currency fingerprints;
6. collision/replay/overlap fail-closed laws;
7. exact WND and XAF frozen values;
8. release-manifest hashes for all non-manifest R4D artifacts.
