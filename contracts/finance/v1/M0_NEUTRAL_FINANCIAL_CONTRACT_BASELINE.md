# XBOS M0 — Approved Neutral Financial Contract Baseline

**Record type:** Executable contract baseline and implementation authority
**Workstream:** Track B-FIN — Neutral Financial Spine
**Checkpoint:** M0.5 — Cross-Catalog Conformance and Baseline Freeze
**Status:** Approved baseline candidate
**Date:** 6 August 2026
**Parent commit:** `a9aacf0`
**Planned tag:** `track-b-m0-neutral-contracts-20260806`

## 1. Decision

The M0.1–M0.4 contracts now form one versioned authority for implementing the XBOS neutral financial kernel. M0.5 binds them together, verifies their cross-references, fingerprints their semantic content, records their test inventory, and defines how future changes must be governed.

The baseline is intentionally neutral. WND will be migrated into it as the first polished Restaurant tenant. WND's historical architecture is evidence for migration, not a permanent constraint on the kernel.

## 2. What is frozen

| Phase | Contract authority |
|---|---|
| M0.1 | Canonical immutable financial-event vocabulary and posting eligibility |
| M0.2 | Neutral account roles and balanced golden posting scenarios |
| M0.3 | Canonical financial entities, ownership, relationships, invariants, and lifecycles |
| M0.4 | Idempotency, concurrency, provider inbox, outbox/inbox, offline replay, and payment-to-fulfillment boundaries |
| M0.5 | Semantic fingerprints, cross-catalog conformance, test inventory, release gate, and implementation precedence |

The machine-readable source is `contract_baseline_manifest.json`.

## 3. Why semantic fingerprints are used

Every catalog in the baseline has a SHA-256 fingerprint calculated from canonical JSON:

```text
UTF-8 + sorted object keys + compact separators + ensure_ascii=false
```

This detects meaningful contract changes while remaining independent of indentation and Windows versus Unix line endings. A developer cannot silently alter a catalog and still pass the baseline suite.

## 4. Cross-catalog guarantees

M0.5 proves that:

- all seven catalogs exist and match their declared code, version, revision, and semantic fingerprint;
- all event posting profiles use declared neutral account roles;
- all golden-scenario events resolve to canonical event types;
- all scenario journal lines use roles bound by that scenario;
- posting-profile references resolve, while intentionally non-posting events remain profile-free;
- all entity relationships point to declared canonical entities within the same tenant;
- all entity lifecycle references resolve to declared state machines;
- lifecycle transitions use declared states;
- outbox delivery states agree across entity, lifecycle, and reliability contracts;
- provider-inbox transitions remain inside the declared state graph;
- workflow financial outputs resolve to the financial-event catalog;
- workflow entity outputs resolve to the entity catalog;
- financial events and workflow events remain separate vocabularies;
- provider evidence, settlement, allocation, confirmation, and fulfillment cannot be collapsed into one shortcut.

## 5. Normative precedence

When sources disagree, implementation decisions follow this order:

1. executable contract tests;
2. machine-readable contract catalogs;
3. approved B2 architecture records;
4. implementation code;
5. historical behavior.

This order is deliberate. Existing code must be refactored when it conflicts with the approved neutral model. Historical WND behavior may be migrated or replaced; it does not overrule the kernel.

## 6. Extension boundary

The baseline supports multiple industries, countries, channels, payment orchestrators, and providers without placing their peculiarities inside the financial core.

- Tenant configuration binds neutral account roles to the tenant's chart of accounts.
- Industry packs define commercial policies and fulfillment workflows.
- Payment adapters normalize provider evidence but cannot post financial truth directly.
- XafPay is one orchestrator adapter, not the only possible route.
- External channels such as WhatsApp may submit commands and observe status but cannot bypass confirmation policy.
- Restaurant, hospitality, retail, and future packs share the same settlement, allocation, accounting, reconciliation, audit, and reliability contracts.

## 7. Change governance

After the baseline tag is created, semantic changes require:

1. an explicit catalog revision or major version;
2. updated golden scenarios where economic behavior changes;
3. updated conformance tests;
4. an impact note covering migrations, adapters, packs, reports, and reconciliation;
5. a new approved baseline manifest and tag.

Implementation work may add database models, migrations, repositories, services, APIs, projections, and adapters without revising the contracts when it faithfully implements the frozen behavior.

## 8. Test baseline

| Suite | Tests |
|---|---:|
| M0.1 event catalog | 18 |
| M0.2 posting scenarios | 18 |
| M0.3 entities and lifecycles | 26 |
| M0.4 reliability and workflows | 38 |
| M0.5 baseline conformance | 30 |
| **Contract tests** | **130** |
| B1 characterization tests | 18 |
| **Complete suite** | **148** |

## 9. Verification commands

After extracting the M0.5 bundle into the repository root, run:

```bat
python -m py_compile tests\contracts\test_financial_contract_baseline.py
python -m pytest tests\contracts\test_financial_contract_baseline.py --collect-only -q
python -m pytest tests\contracts\test_financial_contract_baseline.py -q
python -m pytest tests\contracts -q
python -m pytest --collect-only -q
python -m pytest -q
git diff --check
git status --short --untracked-files=all
```

Expected results:

- 30 M0.5 tests pass;
- 130 contract tests pass;
- 148 complete tests pass;
- the pre-existing deprecation warnings may remain unchanged;
- exactly three new M0.5 files appear before staging;
- no whitespace errors appear.

## 10. Commit and release gate

After successful verification, the intended commit is:

```bat
git commit -m "test: freeze neutral financial contract baseline"
```

After the commit is pushed and the working tree is clean, create the annotated tag:

```bat
git tag -a track-b-m0-neutral-contracts-20260806 -m "Track B M0 approved executable neutral financial contracts"
git push origin track-b-m0-neutral-contracts-20260806
```

The tag must not be created before the full 148-test suite passes on the actual repository.

## 11. Exit gate

M0 is complete when:

```text
All seven neutral financial catalogs match the approved semantic baseline;
all 130 contract tests and all 18 characterization tests pass;
the baseline commit and annotated tag are pushed; and implementation can begin
without unresolved ambiguity about financial authority or workflow boundaries.
```

## 12. Next work

The next phase leaves contract design and enters implementation. Work should begin with the target persistence foundation and safe migration scaffolding defined by the approved B2 physical schema and migration-slice plan, while keeping the M0 contract suite green throughout every slice.
