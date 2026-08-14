# ADR 0016 — SO5 resource identity and assignment remain separate from Party and authentication

## Decision

SO5 owns tenant-scoped operational resources and assignments. A person-backed resource references PC2 Party and may reference a PC5 Identity that has active membership in the tenant. Non-person resources do not create fake Parties. Operational capability/assignment is not a PC5 security role.

PC1 remains structural authority, SO6 remains future generalized workflow authority, SO10 remains future scheduling authority, and Finance remains unchanged.

## Compatibility

Legacy users, branches, role strings and staff snapshots are preserved and may be mapped through explicit compatibility evidence. No production cutover or bulk conversion occurs in SO5.
