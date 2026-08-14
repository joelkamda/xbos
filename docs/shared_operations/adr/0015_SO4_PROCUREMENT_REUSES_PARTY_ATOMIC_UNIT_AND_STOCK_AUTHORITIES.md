# ADR 0015: SO4 reuses supplier, item and stock authorities

Status: Accepted candidate.

SO4 adds only procurement workflow authority. It references PC2 Party and SO2 operational relationships for suppliers, SO1 Atomic Unit for canonical items, and invokes SO3 for stock consequences. Tenant-qualified foreign keys prevent cross-tenant references. Finance remains the sole economic and accounting authority; documents, notifications and generalized scheduling remain future SO7/SO8/SO10 work.
