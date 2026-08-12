# PC2 Party Authority

PC2 establishes one tenant-scoped Party root with exclusive Person and Organization Party subtypes. Party is a business relationship entity; it is not authentication Identity, Tenant, Legal Entity, Organization Unit, Location, or a Finance counterparty snapshot.

## Public authority

Consumers use `core.platform.party.PartyAuthority` with an accepted repository boundary. Exact external identifiers provide unambiguous reference resolution. Name/contact search is deterministic discovery only and never performs identity merging.

Business roles and typed directional relationships are effective-dated. Role context may reference PC1 Legal Entity, Organization Unit, or Location without taking ownership of those records. Organization Party may be linked one-to-one to a PC1 Legal Entity through an explicit link.

## Compatibility

`users` remains PC5 authentication compatibility authority. No user is converted automatically. Legacy person/customer/supplier/staff records require explicit evidence recorded in `party_compatibility_mappings`.

Neutral Finance remains unchanged. `financial_counterparties` keeps its immutable display/contact snapshots and nullable Party candidate reference. PC2 does not backfill or reinterpret Finance records.

## Install and acceptance

The single canonical migration is `pc2_party_authority_022`, a child of `pc1_structural_context_021`. The Windows gate creates `xbos_platform_core_pc2_test` from `template0`, rehearses migration and PC2 behavior, validates downgrade/re-upgrade, then performs controlled development adoption only after disposable proof.

No migration seeds tenants, users, counterparties, or Parties.
