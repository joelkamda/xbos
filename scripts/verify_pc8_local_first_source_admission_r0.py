"""Additive PC8 Local-First source proof, never a release issuer or PC8 override."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REL="contracts/platform/v2/pc8_local_first_source_admission_contract_r0.json"
SCHEMA="XCOMP_PC8_LOCAL_FIRST_PROSPECTIVE_SOURCE_ADMISSION_R0"
WRAPPER="f68e4217395f58afbbb493bf7e772050d865ade8"
W_V2="d5ffbc3c253cbd0530bd15cac1e594a0447bf8e5"
PROTECTED="376547f7c037814ab2b19a1df8fd6c7aec08f864"
REPO="joelkamda/xbos"
BRANCH="review/xcomp-pc8-local-first-v2-source-20261111"
TARGET="platform/neutral-vnext-vn2-pc0-discovery-successor"
EXACT=frozenset({
 "contracts/platform/v2/pc8_local_first_source_admission_contract_r0.json",
 "scripts/verify_pc8_local_first_source_admission_r0.py",
 "tests/contracts/test_pc8_local_first_source_admission_r0.py",
 ".github/workflows/xcomp-pc8-local-first-source-admission.yml"})
HISTORICAL={
 "scripts/verify_pc8_registered_current_source_r1.py":"0dc113e08d646cb7f65f833a370e81a999929aa3356ff7d443f644b89bf6f50e",
 "contracts/platform/v1/pc8_current_source_companion_registry_r1.json":"78374520f4d483866a07d13d99b1993584299c580877b4d422d4b7a646f010c8",
 ".github/workflows/xcomp-pc8-registered-current-source.yml":"62e5691ad81a8b23aea3efe1afb4a812d1b0ae3a2d1cf4909dbe73a4cadda7a5",
 "XBOS_PC8_CURRENT_SOURCE_RUN_ACCEPTANCE.cmd":"ccff3a24b968fef94ddf51e5093c4dc5d9ec7f48cf30ec77459554179826bce0",
 "core/platform/release_integrity.py":"6ded92f7aa0fc0b3db5115ff5094b9e39b521a0d1f05d9ee102b96d668ab0ec4"}
# Independent source pins: do not derive trust from a self-edited JSON.
# These are immutable W-v2 inputs from the accepted PR14 evidence.
QUALIFIED_W_V2={
 "contracts/platform/v2/pc0_local_first_restaurant_successor.json":"8d351639e4f3cd18d663d8494d294510e81021c30b470e53eb2d4200976dc5ef",
 "core/platform/local_first_restaurant_architecture_successor.py":"37a5cbbbe0dd4c3692182d9fb3aa09647f6e3343f07b5e2b0350dae47ef179dc",
 "tests/contracts/test_pc0_local_first_restaurant_successor.py":"15b796340dbf8abddd9a6cd66f3fa7c8085fef2b535a6d3cc837439e1bba69df",
 "core/api/restaurant/local_first_lan_router.py":"7f4487999ffccab39291930394f70351ef3bf4561cd88f518a1ededd108386f2",
 "core/domain/restaurant/local_first_shift_session.py":"77b5f89885dfcc0e4da3e8a3a3b6f3ae4f3437763c5064f9e1a825d5858bf385",
 "core/domain/restaurant/local_first_stock_draft.py":"abffd9e3332a08e42d70c620ce9e61e7906ea51d6219938d81ffc0cfb075489b",
 "core/domain/restaurant/local_first_receipt_service.py":"2eb91ba58b504eece152fd743fc77cf262a187106431b091a74417e42a8f2881",
 "tests/integration/test_xcomp_w_disconnected_pg17_acceptance.py":"cda21a72721c8ae7bef0fc08eeee40f0588856bfccb2bfea658d171d8221ccb5"}

class SourceAdmissionDenied(ValueError):
    pass

def require(ok:bool, reason:str)->None:
    if not ok:raise SourceAdmissionDenied(reason)

def digest(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(root:Path,*args:str)->str:
    p=subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,
                     encoding="utf-8",errors="replace")
    if p.returncode:raise SourceAdmissionDenied("GIT_PROVENANCE_UNAVAILABLE")
    return p.stdout.strip()

def qualify_contract(c:dict)->dict:
    require(isinstance(c,dict) and c.get("schema")==SCHEMA and c.get("version")==1,
            "SOURCE_SCHEMA_DENIED")
    require(c.get("state")=="SOURCE_CANDIDATE_ONLY_UNPUBLISHED"
            and c.get("operative_release") is False
            and c.get("registered") is False
            and c.get("release_issuer_commissioned") is False
            and c.get("no_authority_from_source_tests") is True,
            "OPERATIVE_RELEASE_SELF_PROMOTION_DENIED")
    precedent=c.get("predecessor")
    require(isinstance(precedent,dict) and precedent=={
        "accepted_pr14_wrapper":WRAPPER,"qualified_w_v2":W_V2,
        "protected_base":PROTECTED,"source_repository":REPO,
        "proposed_review_branch":BRANCH,"protected_target":TARGET,
        "historical_pc8_review_branch":"review/xcomp-pc8-route-a-11file-20261108"},
        "SOURCE_BRANCH_OR_PARENT_REWRITTEN")
    require(c.get("immutable_historical_pc8_artifacts")==HISTORICAL,
            "HISTORICAL_PC8_HASH_CUSTODY_DRIFT")
    w=c.get("immutable_qualified_w_v2_files")
    require(isinstance(w,dict) and set(w)==set(QUALIFIED_W_V2)
            and w==QUALIFIED_W_V2,
            "W_V2_CUSTODY_INVENTORY_DRIFT")
    require(c.get("exact_additive_source_paths")==[
        "contracts/platform/v2/pc8_local_first_source_admission_contract_r0.json",
        "scripts/verify_pc8_local_first_source_admission_r0.py",
        "tests/contracts/test_pc8_local_first_source_admission_r0.py",
        ".github/workflows/xcomp-pc8-local-first-source-admission.yml"],
        "UNAPPROVED_SOURCE_PATH_REQUEST")
    trust=c.get("independent_trust")
    require(isinstance(trust,dict) and set(trust)=={
        "issuer_public_key_id","owner_release_signature","pcr_release_signature",
        "required_pc8_attestation","signed_same_commit_deployment","approved_release_epoch"}
        and all(x is None for x in trust.values()),"FORGED_PC8_TRUST")
    required=c.get("required_proofs")
    require(isinstance(required,list) and len(required)==7
            and all(isinstance(x,str) and x for x in required)
            and len(set(required))==7,"REQUIRED_SOURCE_PROOFS_WEAKENED")
    assert_noeffects=["MUTATE_FROZEN_PC0_OR_PC8","REWRITE_PR14",
                      "SOURCE_SELF_AUTHORIZES_RELEASE","GITHUB_PUSH_OR_PR",
                      "RULESET_MUTATION","POSTGRESQL","ISSUER_KEY_CREATION",
                      "RENDER","WND","PAYMENT"]
    require(c.get("prohibited")==assert_noeffects,"PROHIBITED_ACTION_CHANGED")
    return {"status":"QUALIFIED_SOURCE_CANDIDATE_ONLY",
            "operative_release":False,"registered":False,
            "independent_signing_verified":False}

def qualify_event(c:dict, event:dict, *,
                  checkout_sha:str,review_head_sha:str,base_sha:str,
                  tracked_scope:set[str],wrapper_ancestor:bool,
                  exact_merge_checkout:bool)->dict:
    """Pure deny-first event projection. An actual GH run supplies trusted inputs."""
    qualify_contract(c)
    require(isinstance(event,dict), "MISSING_PR_EVENT")
    pr=event.get("pull_request")
    require(isinstance(pr,dict) and isinstance(event.get("repository"),dict),
            "MALFORMED_PR_EVENT")
    head=pr.get("head") or {}
    base=pr.get("base") or {}
    require(event["repository"].get("full_name")==REPO and
            (head.get("repo") or {}).get("full_name")==REPO and
            (base.get("repo") or {}).get("full_name")==REPO,"UNTRUSTED_PR_REPOSITORY")
    require(head.get("ref")==BRANCH and base.get("ref")==TARGET,
            "WRONG_LOCAL_FIRST_REVIEW_BRANCH")
    require(head.get("sha")==review_head_sha and base.get("sha")==base_sha
            and base_sha==PROTECTED,"REVIEW_COMMIT_IDENTITY_DENIED")
    require(isinstance(checkout_sha,str) and re.fullmatch("[0-9a-f]{40}",checkout_sha)
            and checkout_sha!=review_head_sha
            and exact_merge_checkout,"CHECKOUT_MERGE_COMMIT_DENIED")
    require(wrapper_ancestor and tracked_scope==EXACT,
            "WRAPPER_ANCESTRY_OR_SOURCE_SCOPE_DENIED")
    return {"status":"PR_SOURCE_IDENTITY_ONLY","operative_release":False,
            "future_release_authority":False}

def inspect_source(root:Path=ROOT, *, expected_head:str|None=None,
                   require_four_path_delta:bool=False)->dict:
    """Read-only independent local source inspection, no hosted verification."""
    try:c=json.loads((root/REL).read_text(encoding="utf-8"))
    except (OSError,ValueError) as e:raise SourceAdmissionDenied("SOURCE_CONTRACT_UNREADABLE") from e
    result=qualify_contract(c)
    for name,value in HISTORICAL.items():
        path=root/name
        require(path.is_file() and digest(path)==value,
                "FROZEN_PC8_MODIFIED")
    for name,value in c["immutable_qualified_w_v2_files"].items():
        path=root/name
        require(path.is_file() and digest(path)==value,
                "QUALIFIED_W_V2_SOURCE_DRIFT")
        require(git(root,"rev-parse","HEAD:"+name)==git(root,"rev-parse",W_V2+":"+name),
                "W_V2_GIT_BLOB_PROVENANCE_CHANGED")
    head=git(root,"rev-parse","HEAD")
    if expected_head is not None:require(head==expected_head,"WRONG_SOURCE_HEAD")
    git(root,"merge-base","--is-ancestor",WRAPPER,head)
    if require_four_path_delta:
        changed=set(git(root,"diff","--name-only",WRAPPER,head).splitlines())
        require(changed==EXACT,"FOUR_FILE_SOURCE_SCOPE_DENIED")
    return dict(result,source_head=head,source_paths=sorted(EXACT),
                real_github_ci_verified=False,operative_release=False)


def inspect_github_pr_environment(root:Path=ROOT)->dict:
    """Only a genuine future GitHub PR runner can execute this path."""
    import os
    require(os.environ.get("GITHUB_ACTIONS")=="true"
            and os.environ.get("GITHUB_EVENT_NAME")=="pull_request"
            and os.environ.get("GITHUB_REPOSITORY")==REPO,
            "TRUSTED_GITHUB_PR_RUNNER_REQUIRED")
    try:
        event=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError,OSError,ValueError) as exc:
        raise SourceAdmissionDenied("GITHUB_PR_EVENT_UNREADABLE") from exc
    pr=event.get("pull_request") or {}
    require(isinstance(event.get("number"),int)
            and event["number"]>0 and pr.get("number")==event["number"]
            and os.environ.get("GITHUB_REF")==f'refs/pull/{event["number"]}/merge'
            and os.environ.get("GITHUB_HEAD_REF")==BRANCH
            and os.environ.get("GITHUB_BASE_REF")==TARGET,
            "GITHUB_PR_REF_OR_NUMBER_DENIED")
    checkout=git(root,"rev-parse","HEAD")
    require(checkout==os.environ.get("GITHUB_SHA"),"GITHUB_MERGE_SHA_DRIFT")
    head=(pr.get("head") or {}).get("sha")
    base=(pr.get("base") or {}).get("sha")
    require(isinstance(head,str) and re.fullmatch("[0-9a-f]{40}",head)
            and base==PROTECTED,"GITHUB_PR_UNPINNED_HEAD_OR_BASE")
    parents=git(root,"rev-list","--parents","-n","1",checkout).split()
    require(len(parents)==3 and parents==[checkout,base,head],
            "GITHUB_PR_MERGE_PARENTS_DENIED")
    git(root,"merge-base","--is-ancestor",WRAPPER,head)
    changed=set(git(root,"diff","--name-only",WRAPPER,head).splitlines())
    require(changed==EXACT,"GITHUB_SOURCE_PATH_SCOPE_DENIED")
    git(root,"merge-base","--is-ancestor",head,checkout)
    # W/source and 4 new files survive merge without conflict rewrite.
    for name in tuple(QUALIFIED_W_V2)+tuple(EXACT):
        require(git(root,"rev-parse","HEAD:"+name)==
                git(root,"rev-parse",head+":"+name),
                "GITHUB_PR_MERGE_BLOB_DRIFT")
    source=inspect_source(root,require_four_path_delta=False)
    try:c=json.loads((root/REL).read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise SourceAdmissionDenied("SOURCE_CONTRACT_UNREADABLE") from exc
    event_qualification=qualify_event(
        c,event,checkout_sha=checkout,review_head_sha=head,
        base_sha=base,tracked_scope=changed,wrapper_ancestor=True,
        exact_merge_checkout=True)
    return dict(source,event=event_qualification,
                status="GITHUB_PR_SOURCE_QUALIFIED_NONOPERATIVE",
                operative_release=False,real_github_ci_verified=True)

def main()->int:
    import argparse
    parser=argparse.ArgumentParser(description="Prospective Local-First PC8 source proof only")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--local-source",action="store_true")
    group.add_argument("--github-pr-source",action="store_true")
    args=parser.parse_args()
    try:
        result=(inspect_source() if args.local_source
                else inspect_github_pr_environment())
    except (SourceAdmissionDenied,OSError,ValueError) as exc:
        print(json.dumps({"status":"DENIED","reason":str(exc),
                          "operative_release":False},sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
