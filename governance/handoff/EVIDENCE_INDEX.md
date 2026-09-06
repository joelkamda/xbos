# XBOS Succession Evidence Index

## Purpose

This index records durable evidence used to reconstruct XBOS succession state without treating filenames, working-tree material, runtime state, or prior chat memory as authority by themselves.

## Canonical Source Repository

CANONICAL_SOURCE_REPOSITORY=C:\Users\jdkam\XBOS

KNOWN_REMOTE=https://github.com/joelkamda/xbos.git

PHASE_1_VERIFIED_HEAD=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

PHASE_1_VERIFIED_BRANCH=restaurant/r6-4-wnd-production-cutover-package-runbook

LATEST_IMMUTABLE_WND_BASELINE=R6.3_ACCEPTED_UAT

LATEST_IMMUTABLE_WND_TAG=restaurant-r6-3-wnd-application-compatibility-uat-20260822

## Phase 1 Repository Evidence

Phase 1 verified the canonical laptop path is a Git worktree rooted at `C:\Users\jdkam\XBOS`, with HEAD `b97d3850b120aff92261ad9edcb3bf3151ebbcb3` on branch `restaurant/r6-4-wnd-production-cutover-package-runbook`.

The working tree was intentionally not clean because R6.4 continuity material existed and had to be preserved.

Tracked modification observed:

- `restaurant/r6/__init__.py`

Untracked continuity paths observed:

- `R6_4_INSTALL_MANIFEST.txt`
- `XBOS_R6_4_CAPTURE_PLANNING_BASELINE.cmd`
- `XBOS_R6_4_INSTALL_AND_VERIFY.txt`
- `XBOS_R6_4_RUN_ACCEPTANCE.cmd`
- `contracts/restaurant/v1/r6_4_hypercare_retirement_boundary.json`
- `contracts/restaurant/v1/r6_4_production_cutover_package_authority.json`
- `contracts/restaurant/v1/r6_4_r6_5_cutover_runbook.json`
- `contracts/restaurant/v1/r6_4_release_manifest.json`
- `docs.zip`
- `docs/restaurant/R6_4_WND_PRODUCTION_CUTOVER_PACKAGE_AND_RUNBOOK.md`
- `docs/restaurant/adr/0010_R6_4_CUTOVER_BEFORE_LEGACY_WRITER_RETIREMENT.md`
- `restaurant/r6/production_cutover.py`
- `scripts/capture_r6_4_wnd_planning_baseline.py`
- `scripts/verify_r6_4_wnd_production_cutover_package.py`
- `tests/contracts/test_r6_4_wnd_production_cutover_package.py`

The presence of these paths does not prove R6.4 acceptance, freeze, or live cutover authority.

## R6.3 Governing Evidence

Primary tracked R6.3 evidence includes:

- `contracts/restaurant/v1/r6_3_application_compatibility_authority.json`
- `contracts/restaurant/v1/r6_3_legacy_inventory_writer_compatibility.json`
- `contracts/restaurant/v1/r6_3_reference_application_contract.json`
- `contracts/restaurant/v1/r6_3_release_manifest.json`
- `contracts/restaurant/v1/r6_3_uat_matrix.json`
- `contracts/restaurant/v1/r6_3_visual_uat_evidence.json`
- `docs/restaurant/R6_3_WND_APPLICATION_COMPATIBILITY_AND_VISUAL_UAT.md`
- `docs/restaurant/adr/0009_R6_3_EXACT_WND_RELEASE_AS_COMPATIBILITY_ORACLE.md`

R6.3 proves accepted application compatibility and visual UAT. It does not authorize production cutover, production writes, writer-routing change, or legacy-writer retirement. Its next gate is R6.4 deterministic final production cutover package and runbook.

## Neutral Kernel and Composition Evidence

Relevant immutable references include:

- `docs/platform_core/PC6_NEUTRAL_PLATFORM_PROOF_AND_FREEZE.md`
- `contracts/platform/v1/pc6_neutral_platform_proof.json`
- `docs/packs/adr/0025_PK_AGGREGATE_FREEZE_AND_COMPOSITION_BOUNDARY.md`
- `docs/restaurant/R4_RESTAURANT_PACK_REGISTRATION.md`
- `docs/restaurant/adr/0005_R4_RESTAURANT_PACK_REGISTRATION_BOUNDARY.md`
- `docs/restaurant/R5_WND_TENANT_PROFILE_AND_TEMPLATE_PROOF.md`
- `docs/restaurant/adr/0006_R5_WND_TENANT_TEMPLATE_COMPOSITION_BOUNDARY.md`

These support:

NEUTRAL_KERNEL=FROZEN_PROVEN

RESTAURANT_PACK=FROZEN_PROVEN

WND_TENANT_COMPOSITION=PROVEN

## R6.4 Working-Tree Continuity Evidence

R6_4_STATE=UNCOMMITTED_WORKTREE_CONTINUITY_NOT_PROVEN_ACCEPTED

R6_4_ACCEPTANCE=NOT_PROVEN

R6_4_FREEZE=NOT_PROVEN

R6_4_REPAIR_AUTHORIZED=NO

The untracked R6.4 material describes planning/rehearsal and an intended R6.5 compatibility-mode cutover, but it is continuity evidence rather than immutable laptop authority.

No R6.4 acceptance result or planning-baseline pointer was found in the laptop Downloads evidence search.

## R6.4 Manifest Discrepancy

R6_4_WORKTREE_PACKAGE=MANIFEST_MISMATCH

R6_4_PACKAGE_COHERENCE=VERIFY_REQUIRED

DISCREPANCY_CLASS=KNOWN_UNRESOLVED_EVIDENCE_DISCREPANCY

Five R6.4 files had manifest SHA256 mismatches. PCR closed the discrepancy for succession without classifying it as corruption, acceptance, freeze, or repair authority.

No further hash investigation is required unless PCR explicitly reopens it.

## Roadmap State

A0=VERIFY_REQUIRED

F_SERIES=VERIFY_REQUIRED

FINAL_WND_MIGRATION_STATE=NOT_PROVEN_AT_IMMUTABLE_LAPTOP_BASELINE

R6_5_STATE=NOT_PROVEN_FROM_LAPTOP_GIT

## WND External Environment

WND_PRODUCTION_CONTROL_SOURCE=C:\Users\wndine\XBOS_R6_4_CONTROL

WND_LIVE_RUNTIME=C:\Users\wndine\XBOS_R6_5_LIVE

WND_PRODUCTION_CONTROL_STATE=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

WND_LIVE_RUNTIME_STATE=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

WND_LIVE_RUNTIME_IS_SOURCE_AUTHORITY=NO

External WND verification is deferred until WND access is available.

## Evidence Precedence

1. explicit current PCR authority
2. installed living handoff verified against repository evidence
3. immutable repository evidence
4. fresh live Git verification
5. verified external WND production-control evidence
6. working-tree continuity evidence
7. historical narrative or prior-chat context

SUCCESSION_PASS != LIVE_EXECUTION_VERIFIED


## Succession Installation Event — Foundation

INSTALLATION_MODEL=CANONICAL_WORKTREE_GUARDED_SCRIPT

FOUNDATION_PARENT=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

FOUNDATION_COMMIT=THIS_COMMIT_RESOLVE_FROM_GIT

SUCCESSION_FOUNDATION=INSTALLED_PENDING_START_HERE

XBOS_START_HERE_PRESENT=NO

R6_4_CONTINUITY_PRESERVATION=MANDATORY

DOMAIN_SOURCE_INCLUDED=NO

SCHEMA_INCLUDED=NO

The installer must verify the exact protected R6.4 status/path set and capture a raw-byte fingerprint before any succession write, then prove the protected fingerprint is unchanged after every commit boundary.
