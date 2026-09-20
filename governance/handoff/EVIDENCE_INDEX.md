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


## Succession Installation Evidence

INSTALLATION_MODEL=CANONICAL_WORKTREE_GUARDED_SCRIPT

FOUNDATION_PARENT=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

FOUNDATION_COMMIT=416f6cbf19a2fbd28859a98a03ca6004bc930cc5

XBOS_START_HERE_COMMIT=4678757e80c9313b6fb04cf5711f99dc9dc56d29

FINAL_SYNC_COMMIT=THIS_COMMIT_RESOLVE_FROM_GIT

SUCCESSION_FOUNDATION=INSTALLED

XBOS_START_HERE_PRESENT=YES

XBOS_START_HERE_STATE=INSTALLED_ACCEPTED_PENDING_COLD_START_TEST

SUCCESSION_STATE=COLD_START_TEST_PENDING

R6_4_CONTINUITY_PRESERVED=REQUIRED_PASS_FROM_INSTALLER_FINAL_EVIDENCE

DOMAIN_SOURCE_INCLUDED_IN_SUCCESSION_COMMITS=NO

SCHEMA_INCLUDED_IN_SUCCESSION_COMMITS=NO

TAG_AUTHORIZED=NO

PUSH_AUTHORIZED=NO

NEXT_AUTHORIZED_ACTION=RUN_FRESH_XBOS_COLD_START_SUCCESSION_TEST_AND_RETURN_RESULT_TO_PCR

The succession commits advance governance continuity HEAD only. They do not alter the immutable R6.3 domain baseline and do not make preserved R6.4 working-tree material accepted, frozen, or authorized.


## G02-C2 Accepted Frozen Remote-Published Evidence — 2026-09-20

C2_WORKTREE=C:\Users\jdkam\XBOS_G02_C2_SAFE_ORDER_LINE_REMOVAL

C2_BRANCH=platform/g02-c2-safe-order-line-removal

C2_ACCEPTED_SHA=6eb460107a45aa0d0380546002ff2d385cc609a8

C2_PARENT_SHA=21103cb9c1d5fc19ba03879fc6092ec23151410d

C2_ACCEPTANCE_TAG=xbos-g02-c2-safe-order-line-removal-accepted-20260920

C2_REMOTE_BRANCH_TARGET=6eb460107a45aa0d0380546002ff2d385cc609a8

C2_REMOTE_TAG_TARGET=6eb460107a45aa0d0380546002ff2d385cc609a8

C2_MIGRATION_REVISION=r1_restaurant_order_line_lifecycle_046

C2_MIGRATION_PARENT=ia0_neutral_interaction_authority_045

D2_ACCEPTANCE_EVIDENCE=PASS_ACCEPTED

F1_ACCEPTANCE_FREEZE_EVIDENCE=PASS_ACCEPTED

P1_ATOMIC_PUBLICATION_EVIDENCE=PASS_ACCEPTED

COLD_START_RECONSTRUCTION_EVIDENCE=PASS_ACCEPTED

R1_R2_CONTRACT_ACCEPTANCE=58_PASS

RELEASE_INTEGRITY_ACCEPTANCE=67_PASS

SO1_VERIFIER=PASS

SAFE_LINE_REMOVAL=PASS_ACCEPTED

REMOVED_LINE_PROJECTION_EXCLUSION=PASS_ACCEPTED

PREPARATION_GUARD=PASS_ACCEPTED

TAB_PARTITION_GUARD=PASS_ACCEPTED

HISTORY_PRESERVATION=PASS_ACCEPTED

C2_DEPLOYED=NO

WND_LIVE_RUNTIME_STATE=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

LAST_PROVEN_WND_RUNTIME_DATE=2026-09-15

LAST_PROVEN_WND_RUNTIME=RUNNING_ACCEPTED_PRE_CUTOVER_RUNTIME

### Canonical R6.4 Ref Discrepancy Observation

CANONICAL_BRANCH=restaurant/r6-4-wnd-production-cutover-package-runbook

CANONICAL_PRE_HS1_LOCAL_SHA=8962b68696c61a2ab15f678eeef2796a7c98f6cb

CANONICAL_CACHED_ORIGIN_SHA=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

CANONICAL_ACTUAL_REMOTE_SHA=ee58b8d0ce12ab708a1aa894c73bfb303f1f6fbf

ACTUAL_REMOTE_OBJECT_PRESENT_LOCALLY=NO

CANONICAL_REMOTE_RELATIONSHIP=UNRESOLVED

CANONICAL_REF_DISCREPANCY=QUARANTINED_SEPARATE_FROM_G02_C2

ANCESTRY_CLAIM=NONE

CANONICAL_FETCH=NO

CANONICAL_PUSH=NO

NEXT_RECOMMENDED_GATE=XBOS-CANONICAL-R6_4-REMOTE-REF-RECONCILIATION-PREFLIGHT
