"""Prospective source and negative controls: never operative PC8 approval."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts.verify_pc8_local_first_source_admission_r0 import (
 ROOT,REL,HISTORICAL,QUALIFIED_W_V2,EXACT,WRAPPER,PROTECTED,BRANCH,TARGET,REPO,
 SourceAdmissionDenied,qualify_contract,qualify_event,inspect_source,
 inspect_github_pr_environment)

C=json.loads((ROOT/REL).read_text(encoding="utf-8"))

def good_event():
    return {
      "repository":{"full_name":REPO},"number":14,
      "pull_request":{"number":14,
        "head":{"ref":BRANCH,"sha":"b"*40,"repo":{"full_name":REPO}},
        "base":{"ref":TARGET,"sha":PROTECTED,"repo":{"full_name":REPO}}}}

ARGS=dict(checkout_sha="a"*40,review_head_sha="b"*40,
          base_sha=PROTECTED,tracked_scope=EXACT,
          wrapper_ancestor=True,exact_merge_checkout=True)

def test_source_contract_is_denial_only():
    value=qualify_contract(C)
    assert value["operative_release"] is False
    assert value["independent_signing_verified"] is False
    assert value["status"]=="QUALIFIED_SOURCE_CANDIDATE_ONLY"

def test_exact_pc8_immutable_source_inventory():
    assert len(HISTORICAL)==5 and len(QUALIFIED_W_V2)==8
    result=inspect_source(ROOT)
    import subprocess
    actual=subprocess.check_output(
        ["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
    assert result["source_head"]==actual
    assert not result["real_github_ci_verified"]
    assert result["operative_release"] is False

@pytest.mark.parametrize("field,value",[
 ("operative_release",True),("registered",True),
 ("release_issuer_commissioned",True),
 ("no_authority_from_source_tests",False),
 ("state","OPERATIVE_RELEASE"),
 ("schema","PC8_HISTORICAL_GATE"),
 ("version",2)])
def test_self_promotion_and_schema_changes_denied(field,value):
    x=deepcopy(C);x[field]=value
    with pytest.raises(SourceAdmissionDenied):
        qualify_contract(x)

@pytest.mark.parametrize("field,value",[
 ("accepted_pr14_wrapper","0"*40),
 ("qualified_w_v2","1"*40),
 ("protected_base","2"*40),
 ("source_repository","attacker/xbos"),
 ("proposed_review_branch","main"),
 ("protected_target","main"),
 ("historical_pc8_review_branch","review/xcomp-pc0-v2-w-source-20261111")])
def test_provenance_mutation_denied(field,value):
    x=deepcopy(C);x["predecessor"][field]=value
    with pytest.raises(SourceAdmissionDenied,match="SOURCE_BRANCH_OR_PARENT_REWRITTEN"):
        qualify_contract(x)

def test_historical_digest_rebinding_denied():
    x=deepcopy(C)
    key=next(iter(HISTORICAL))
    x["immutable_historical_pc8_artifacts"][key]="f"*64
    with pytest.raises(SourceAdmissionDenied,match="HISTORICAL_PC8_HASH_CUSTODY_DRIFT"):
        qualify_contract(x)

def test_qualified_w_digest_rebinding_denied():
    x=deepcopy(C)
    key=next(iter(QUALIFIED_W_V2))
    x["immutable_qualified_w_v2_files"][key]="f"*64
    with pytest.raises(SourceAdmissionDenied,match="W_V2_CUSTODY_INVENTORY_DRIFT"):
        qualify_contract(x)

def test_extra_source_path_denied():
    x=deepcopy(C)
    x["exact_additive_source_paths"].append("core/platform/release_integrity.py")
    with pytest.raises(SourceAdmissionDenied,match="UNAPPROVED_SOURCE_PATH_REQUEST"):
        qualify_contract(x)

def test_signer_receipt_forgery_denied():
    x=deepcopy(C)
    x["independent_trust"]["owner_release_signature"]="fake"
    with pytest.raises(SourceAdmissionDenied,match="FORGED_PC8_TRUST"):
        qualify_contract(x)

def test_prohibited_actions_cannot_be_silently_removed():
    x=deepcopy(C);x["prohibited"].remove("GITHUB_PUSH_OR_PR")
    with pytest.raises(SourceAdmissionDenied,match="PROHIBITED_ACTION_CHANGED"):
        qualify_contract(x)

def test_pure_pr_event_source_proof_is_nonoperative():
    result=qualify_event(C,good_event(),**ARGS)
    assert result["status"]=="PR_SOURCE_IDENTITY_ONLY"
    assert result["operative_release"] is False

@pytest.mark.parametrize("mutation",[
 lambda e:e["repository"].update(full_name="attacker/xbos"),
 lambda e:e["pull_request"]["head"].update(ref="main"),
 lambda e:e["pull_request"]["base"].update(ref="main"),
 lambda e:e["pull_request"]["head"]["repo"].update(full_name="attacker/xbos"),
 lambda e:e["pull_request"]["base"]["repo"].update(full_name="attacker/xbos"),
 lambda e:e["pull_request"]["head"].update(sha="c"*40),
 lambda e:e["pull_request"]["base"].update(sha="d"*40)])
def test_pr_event_substitution_denied(mutation):
    e=good_event();mutation(e)
    with pytest.raises(SourceAdmissionDenied):
        qualify_event(C,e,**ARGS)

@pytest.mark.parametrize("change",[
 {"checkout_sha":"b"*40},
 {"wrapper_ancestor":False},
 {"tracked_scope":set()},
 {"tracked_scope":EXACT|{"core/platform/release_integrity.py"}},
 {"exact_merge_checkout":False},
 {"base_sha":"f"*40}])
def test_no_fake_merge_or_scope_denied(change):
    with pytest.raises(SourceAdmissionDenied):
        qualify_event(C,good_event(),**{**ARGS,**change})

def test_github_mode_without_real_runner_is_denied(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    with pytest.raises(SourceAdmissionDenied,match="TRUSTED_GITHUB_PR_RUNNER_REQUIRED"):
        inspect_github_pr_environment(ROOT)

def test_committed_four_file_gate_never_promotes_uncommitted_source():
    # Local precommit worktree and reviewed descendant are distinct states.
    import subprocess
    head=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
    if head==WRAPPER:
        with pytest.raises(SourceAdmissionDenied,match="FOUR_FILE_SOURCE_SCOPE_DENIED"):
            inspect_source(ROOT,require_four_path_delta=True)
    else:
        receipt=inspect_source(ROOT,require_four_path_delta=True)
        assert receipt["operative_release"] is False
        assert receipt["source_head"]==head
