# SO2 CRM / Operational Party Relationships

SO2 owns the tenant-scoped operational relationship around an existing PC2 Party. It does not own person or organization identity, authentication Identity, authorization roles, semantic concepts, canonical contact values, audit truth or financial truth.

The aggregate key is tenant + PC2 Party + neutral relationship type. Relationship types are open tenant/pack capability codes; the only source-level lifecycle states are `prospect`, `active`, `inactive` and `ended`. Every state change appends ordered history. Preference metadata may describe an operationally preferred method or purpose, but email, phone, postal values and consent remain outside SO2.

PC3 classification is invoked through `subject_type=so2_operational_relationship`. PC5 authorization is evaluated before every public command/query. PC1 validates optional organization-unit/location scope. XA metadata describes projections and actions but never grants permission or invents transitions.

Legacy customer/supplier/vendor evidence is preserved and explicitly mapped. The migration performs no backfill, bulk rewrite, WND cutover, Party mutation, Finance write or seed. General communications remain SO8; packs may declare terminology and semantic requirements but no PK lifecycle is implemented.

Install from the repository root, in the approved active Python environment, using `Expand-Archive -Force`, then run `XBOS_SO2_RUN_ACCEPTANCE.cmd`. PostgreSQL acceptance requires local `xbos_track_b_dev`; it rehearses a `template0` database before resumable development adoption.
