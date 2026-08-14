# ADR 0012: Adopt Atomic Unit identity and separate catalog, offer and price

Status: Accepted candidate for operator gate

## Decision

The existing `atomic_units.id` is canonical SO1 internal identity because taxonomy, inventory, sales, orders, reports and compatibility services already reference it. SO1 adds a stable public UUID and optimistic version without replacing or renumbering it.

Catalogs govern discoverability, offers govern presentable composition, and prices govern effective operational commercial amounts. Each has a distinct identity. Taxonomy remains PC3 authority, inventory remains future SO3 authority, Finance remains financial truth, and frontend experience remains XA authority.

The migration is additive from `pc5_identity_policy_audit_025` to `so1_atomic_catalog_offer_pricing_026`. Downgrade removes only SO1 additions and preserves original Atomic Unit IDs and compatibility rows.

## Consequences

- Legacy references remain valid and can move to public UUIDs over governed cutovers.
- Multiple taxonomy placements remain valid.
- Packs may declare composition and terminology without changing SO1 source.
- Price definition creates no revenue, journal, obligation, settlement or reconciliation fact.
- Cross-tenant component, catalog, taxonomy and price references fail.
