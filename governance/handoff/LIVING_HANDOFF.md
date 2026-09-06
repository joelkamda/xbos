# XBOS Living Handoff

## Purpose

This file is the moving succession-state authority for the XBOS lane. A fresh XBOS lane instance enters through `XBOS_START_HERE.md`, reads this file completely first, verifies current repository evidence, and reports authority state before taking action.

## Lane and Baseline

LANE=XBOS

CANONICAL_SOURCE_REPOSITORY=C:\Users\jdkam\XBOS

DOMAIN_BASELINE=R6.3_ACCEPTED_UAT

DOMAIN_BASELINE_COMMIT=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

DOMAIN_BASELINE_TAG=restaurant-r6-3-wnd-application-compatibility-uat-20260822

ACTIVE_TRANCHE=XBOS_SUCCESSION_COLD_START_ACCEPTANCE

CURRENT_REPOSITORY_HEAD=VERIFY_LIVE

CURRENT_STATE=SUCCESSION_INSTALLED_COLD_START_TEST_PENDING_R6_4_UNCOMMITTED_CONTINUITY_R6_5_NOT_PROVEN

## Current Authority State

IMPLEMENTATION_AUTHORIZED=NO

FREEZE_AUTHORIZED=NO

REPOSITORY_MUTATION_AUTHORIZED=NO_UNLESS_EXPLICIT_CURRENT_AUTHORITY

R6_4_REPAIR_AUTHORIZED=NO

WND_LIVE_DEPLOYMENT_AUTHORIZED=NO

A0=VERIFY_REQUIRED

F_SERIES=VERIFY_REQUIRED

RETURN_TO=PCR

## Proven Domain State

NEUTRAL_KERNEL=FROZEN_PROVEN

RESTAURANT_PACK=FROZEN_PROVEN

WND_TENANT_COMPOSITION=PROVEN

R6_4_STATE=UNCOMMITTED_WORKTREE_CONTINUITY_NOT_PROVEN_ACCEPTED

R6_4_WORKTREE_PACKAGE=MANIFEST_MISMATCH

R6_4_PACKAGE_COHERENCE=VERIFY_REQUIRED

R6_4_ACCEPTANCE=NOT_PROVEN

R6_4_FREEZE=NOT_PROVEN

R6_5_STATE=NOT_PROVEN_FROM_LAPTOP_GIT

LEGACY_RETIREMENT=NOT_AUTHORIZED_BY_AVAILABLE_LAPTOP_EVIDENCE

WND_PRODUCTION_CONTROL_STATE=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

WND_LIVE_RUNTIME_STATE=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

## Succession State

SUCCESSION_FOUNDATION=INSTALLED

XBOS_START_HERE_PRESENT=YES

XBOS_START_HERE_STATE=INSTALLED_ACCEPTED_PENDING_COLD_START_TEST

XBOS_START_HERE_COMMIT=4678757e80c9313b6fb04cf5711f99dc9dc56d29

SUCCESSION_STATE=COLD_START_TEST_PENDING

SUCCESSION_FOUNDATION_PARENT=b97d3850b120aff92261ad9edcb3bf3151ebbcb3

SUCCESSION_FOUNDATION_COMMIT=416f6cbf19a2fbd28859a98a03ca6004bc930cc5

KNOWN_R6_4_CONTINUITY=PRESERVED_EXACTLY_AT_INSTALLER_COMPLETION

NEXT_AUTHORIZED_ACTION=RUN_FRESH_XBOS_COLD_START_SUCCESSION_TEST_AND_RETURN_RESULT_TO_PCR

## Permanent Topology

SOURCE_REPOSITORY=C:\Users\jdkam\XBOS

WND_PRODUCTION_CONTROL_SOURCE=C:\Users\wndine\XBOS_R6_4_CONTROL

WND_LIVE_RUNTIME=C:\Users\wndine\XBOS_R6_5_LIVE

WND_LIVE_RUNTIME_IS_SOURCE_AUTHORITY=NO

The laptop source repository is the canonical XBOS source authority.

The WND production-control source is a separate production-control context whose repository relationship to the laptop source must be verified from live evidence when WND access is available.

The WND live runtime is runtime state, not source authority. Deployment authority is separate from source authority.

## Domain Boundaries

WND != XBOS

TENANT_CONFIGURATION != NEUTRAL_KERNEL

INDUSTRY_PACK != TENANT_CONFIGURATION

XBOS_COMMERCIAL_TRUTH != CORE_MONETARY_TRUTH

XBOS_PAYMENT_ORCHESTRATION != GATEWAY_PROVIDER_EXECUTION_AUTHORITY

XBOS_PAYMENT_STATUS != CORE_LEDGER_TRUTH

LIVE_RUNTIME != SOURCE_REPOSITORY

NEUTRAL_XBOS_KERNEL + INDUSTRY_PACK + TENANT_CONFIGURATION = DEPLOYED_BUSINESS_SYSTEM

WND is a proving tenant and production specimen. It is not the definition of the neutral XBOS kernel or the Restaurant industry pack.

## Immutable Domain Baseline Versus Succession Head

The succession commits advance Git HEAD for governance continuity only.

DOMAIN_BASELINE != SUCCESSION_CONTINUITY_HEAD

R6.3 accepted UAT remains the immutable domain baseline at `b97d3850b120aff92261ad9edcb3bf3151ebbcb3`.

The preserved R6.4 working tree does not become accepted, frozen, or authorized because governance succession commits exist above the domain baseline.

## R6.4 Continuity Boundary

Five R6.4 package files have known SHA256 mismatches against the untracked R6.4 release manifest. PCR closed these for succession as a known unresolved evidence discrepancy.

Do not classify the mismatch as repository corruption, acceptance, freeze, or repair authority.

No further R6.4 hash investigation is required for succession unless PCR explicitly reopens it.

## WND External Verification

WND_PRODUCTION_CONTROL_VERIFICATION=DEFERRED_UNTIL_WND_ACCESS

WND_LIVE_RUNTIME_VERIFICATION=DEFERRED_UNTIL_WND_ACCESS

THIS_DEFERRED_VERIFICATION_BLOCKS_LAPTOP_SUCCESSION_INSTALL=NO

REQUIRED_HANDOFF_CLASSIFICATION=VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

## Two-Gate Succession Rule

Gate 1 is succession reconstruction.

Gate 2 is live Git verification immediately before any authorized mutation.

SUCCESSION_PASS != LIVE_EXECUTION_VERIFIED

Before mutation, verify the canonical repository live again. If live evidence conflicts with this handoff or PCR authority, fail closed and return to PCR.

## Bootstrap Return

A fresh XBOS lane instance must first report, without mutation:

HANDOFF_READ=
LANE=
CURRENT_BASELINE=
CURRENT_REPOSITORY_HEAD=
ACTIVE_TRANCHE=
CURRENT_STATE=
IMPLEMENTATION_AUTHORIZED=
FREEZE_AUTHORIZED=
CURRENT_BRANCH=
CURRENT_WORKTREE=
BLOCKERS=
NEXT_AUTHORIZED_ACTION=
RETURN_TO=

It must also state whether current repository evidence is internally consistent with this living handoff.

## Evidence Navigation

Use `governance/handoff/EVIDENCE_INDEX.md` for evidence navigation.

Use `governance/handoff/DECISION_HISTORY.md` for governing decisions.

Do not infer current authority from filenames alone.
