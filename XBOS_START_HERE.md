# XBOS Start Here

## Stable Front Door

This file is the stable bootstrap entry point for a fresh XBOS lane instance.

It is a bootstrap front door, not domain execution authority. Moving state and current execution authority belong in `governance/handoff/LIVING_HANDOFF.md`.

## Bootstrap Protocol

1. Read `governance/handoff/LIVING_HANDOFF.md` completely first.
2. Treat the living handoff as the current XBOS lane state authority unless newer immutable repository evidence or explicit PCR authority contradicts it.
3. Read `governance/handoff/EVIDENCE_INDEX.md` to verify the active baseline, topology, and evidence chain.
4. Read `governance/handoff/DECISION_HISTORY.md` when a governing decision, authority boundary, or succession-state transition needs explanation.
5. Reconstruct current state from repository evidence before proposing any action.
6. Never infer authority from filenames alone.
7. Never infer source authority from the WND live runtime.
8. Fail closed on contradiction or missing evidence.
9. Report the required bootstrap markers before taking action.

## Canonical Repository

CANONICAL_SOURCE_REPOSITORY=C:\Users\jdkam\XBOS

The canonical source repository is distinct from the WND production-control source and WND live runtime.

## Permanent Topology

SOURCE_REPOSITORY=C:\Users\jdkam\XBOS

WND_PRODUCTION_CONTROL_SOURCE=C:\Users\wndine\XBOS_R6_4_CONTROL

WND_LIVE_RUNTIME=C:\Users\wndine\XBOS_R6_5_LIVE

WND_LIVE_RUNTIME_IS_SOURCE_AUTHORITY=NO

Do not conflate these locations.

## Permanent Domain Boundaries

WND != XBOS

TENANT_CONFIGURATION != NEUTRAL_KERNEL

INDUSTRY_PACK != TENANT_CONFIGURATION

XBOS_COMMERCIAL_TRUTH != CORE_MONETARY_TRUTH

XBOS_PAYMENT_ORCHESTRATION != GATEWAY_PROVIDER_EXECUTION_AUTHORITY

XBOS_PAYMENT_STATUS != CORE_LEDGER_TRUTH

LIVE_RUNTIME != SOURCE_REPOSITORY

Neutral deployment composition remains:

NEUTRAL_XBOS_KERNEL + INDUSTRY_PACK + TENANT_CONFIGURATION = DEPLOYED_BUSINESS_SYSTEM

## Authority Discipline

A successful succession reconstruction is not mutation authority.

SUCCESSION_PASS != LIVE_EXECUTION_VERIFIED

Before any authorized repository mutation, perform fresh live Git verification immediately before mutation.

At minimum verify:

- repository is a Git worktree
- canonical toplevel
- remote
- current branch
- current HEAD
- tracked status
- staging
- untracked files
- worktree topology
- tags at HEAD
- PCR-specified parent constraint

If anything material differs from the living handoff or current PCR authority, stop and return to PCR.

## WND External Environment Rule

If the WND production-control machine or live runtime is unavailable, classify unresolved WND facts as:

VERIFY_REQUIRED_EXTERNAL_ENVIRONMENT

Do not fabricate exact WND branch, HEAD, repository relationship, or runtime state.

Deferred WND verification does not by itself authorize any WND mutation.

## Current-State Placement Rule

Keep moving state in `governance/handoff/LIVING_HANDOFF.md`.

Keep durable evidence navigation in `governance/handoff/EVIDENCE_INDEX.md`.

Keep governing decisions in `governance/handoff/DECISION_HISTORY.md`.

Keep this `XBOS_START_HERE.md` stable.

Do not turn this file into a frequently edited status dump.

## Required Bootstrap Return

Before implementation, mutation, deployment, architecture change, freeze, A0 work, F-series work, or R6.4 repair, return:

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

Also state whether current repository evidence is internally consistent with the living handoff.

## Hard Safety Rules

Succession or bootstrap context alone authorizes no mutation.

Stage, commit, branch creation, worktree creation, tag, push, source edit, schema edit, governance edit, and deployment require explicit current authority.

Reset, clean, restore, rebase, merge, pull, and fetch-and-integrate also require explicit current authority and must never be inferred from succession success.

Do not run implementation agents merely because succession reconstruction succeeded.

Do not change architecture from succession context alone.

Do not repair R6.4 unless PCR explicitly authorizes repair.

Do not advance A0 or F-series merely because roadmap material exists.

Do not mutate WND production control or the WND live runtime unless explicit current deployment or production authority permits it.

## Evidence Precedence

Use authority in this order:

1. explicit current PCR authority
2. current installed living handoff, verified against repository evidence
3. immutable repository evidence
4. fresh live Git verification
5. verified external WND production-control evidence
6. working-tree continuity evidence
7. historical narrative or prior-chat context

If a lower-precedence source conflicts with a higher-precedence source, do not silently reconcile it.

## Return Authority

PCR is the cross-lane coordination authority.

RETURN_TO=PCR

Cross-project coordination must occur through explicit PCR handoffs. Do not mutate Gateway, Core, Wallet, Customer Channel, XafShop, or other project repositories from the XBOS lane.
