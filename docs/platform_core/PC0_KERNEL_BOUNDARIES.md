# PC0 Kernel Ownership and Boundary Contract

PC0 establishes enforceable ownership and modular-monolith law without changing schema, runtime composition, routing, middleware order, API behavior, or any frozen Neutral Finance contract.

## Contract set

The authoritative machine-readable contracts are under `contracts/platform/v1/`:

- `pc0_module_map.json` maps every governed production source root to one module owner.
- `pc0_data_authority_register.json` assigns one declared owner to every inventoried data authority.
- `pc0_reference_authority_migration_register.json` records current and target authority, compatibility path, and retirement accountability.
- `pc0_dependency_policy.json` is default-deny and lists allowed module directions.
- `pc0_public_private_interfaces.json` declares module interfaces without creating runtime APIs.
- `pc0_legacy_exception_baseline.json` is the exact, non-wildcard legacy exception set.
- `pc0_composition_baseline.json` freezes startup, router, middleware, ORM registration, and entrypoint evidence.
- `pc0_frozen_finance_baseline.json` freezes Finance source, contracts, Alembic lineage, and schema-neutral boundaries.
- `pc0_frozen_finance_inventory.json` enumerates every protected file and the only recognized transient cache classes.
- `pc0_kernel_boundaries.json` is the PC0 scope and acceptance contract.
- `pc0_release_manifest.json` gives exact hashes for the release artifacts.

## Enforcement semantics

All governed Python files are parsed statically. Internal imports become source-module/target-module edges. An edge passes only when the dependency policy explicitly allows it or all four fields match one named legacy exception: source path, imported name, source module, and target module. Every baseline exception must still be observed; unused or silently broadened exceptions fail verification.

The verifier also proves interface/register coverage, composition fingerprints and markers, all three frozen Finance tree fingerprints, the full 20-revision Alembic lineage, and canonical head `m64_reconciliation_controls_020`. Frozen-source fingerprints use Git-canonical LF bytes so checkout newline policy cannot create a false source change; any content change still fails. Finance fingerprints use an explicit frozen file inventory: missing, changed, or additional source files fail, while bytecode and named interpreter/test cache directories do not participate. Unknown files are not generally ignored. The composition hash inventory must exactly equal the module map's composition-file inventory. The verifier never imports `startup.py` and performs no database access unless the operator explicitly supplies `--development`; that mode executes read-only queries and rolls back.

## Operability gap

The frozen repository has no production dependency authority. PC0 records that gap and does not invent a dependency manifest or lock file. Dependency-authority remediation remains owned by Platform Operations at milestone E5.

## Verification

Run `XBOS_PC0_RUN_ACCEPTANCE.cmd` from an operator checkout at the verified frozen checkpoint with its already-configured development environment. The only accepted success marker is `PC0_SINGLE_GATE=PASS`.
