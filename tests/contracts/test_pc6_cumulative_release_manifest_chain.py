"""Final cumulative PC0→PC6 release-integrity and freeze proof."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.platform.release_integrity import (
    canonical_bytes, canonical_sha256, latest_release, release_chain,
    verify_historical_release, verify_latest_release,
)

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/platform/v1"


def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))


def test_pc6_is_contiguous_latest_descendant_with_no_new_head():
    chain=release_chain(ROOT)
    assert [number for number,_ in chain]==[1,2,3,4,5,6]
    assert chain[-1][1]["previous_head"]==chain[-1][1]["accepted_head"]=="pc5_identity_policy_audit_025"
    assert chain[-1][1]["migration_count"]==0


def test_every_historical_platform_core_release_resolves_exactly_through_pc6():
    reports=[verify_historical_release(ROOT,number) for number in range(1,6)]
    assert [report["latest"] for report in reports]==[6]*5
    assert all(report["replacement_count"]>0 for report in reports)


def test_pc6_manifest_exactly_fingerprints_every_current_release_artifact():
    number,manifest=latest_release(ROOT)
    assert number==6 and verify_latest_release(ROOT)["artifact_count"]==len(manifest["artifacts"])
    assert len({item["path"] for item in manifest["artifacts"]})==len(manifest["artifacts"])


def test_dependency_profile_and_verifier_arbitrary_mutations_fail():
    artifacts={item["path"]:item["sha256"] for item in _json("pc6_release_manifest.json")["artifacts"]}
    for relative in ("requirements-prod.txt","profiles/platform_core/pc6_second_tenant.json","core/platform/neutral_proof/service.py","scripts/verify_pc6_neutral_platform.py"):
        mutated=canonical_bytes((ROOT/relative).read_bytes()+b"unauthorized",artifact_kind="text")
        assert hashlib.sha256(mutated).hexdigest()!=artifacts[relative]


def test_crlf_only_normalization_remains_exact_and_whitespace_is_not_hidden():
    lf=b"authority = 'pc6'\n";crlf=lf.replace(b"\n",b"\r\n")
    assert canonical_bytes(lf,artifact_kind="text")==canonical_bytes(crlf,artifact_kind="text")==lf
    assert canonical_bytes(b"authority  = 'pc6'\n",artifact_kind="text")!=lf
    binary=b"\x00\r\n\xff";assert canonical_bytes(binary,artifact_kind="binary")==binary


def test_historical_heads_and_finance_freeze_remain_immutable():
    expected=["pc1_structural_context_021","pc2_party_authority_022","pc3_semantic_authority_023","pc4_operating_context_024","pc5_identity_policy_audit_025","pc5_identity_policy_audit_025"]
    assert [_json(f"pc{number}_release_manifest.json")["accepted_head"] for number in range(1,7)]==expected
    baseline=_json("pc0_frozen_finance_baseline.json")
    assert baseline["canonical_head"]==baseline["lineage"][-1]=="m64_reconciliation_controls_020"
    assert canonical_sha256(CONTRACTS/"pc0_frozen_finance_baseline.json",relative_path="contracts/platform/v1/pc0_frozen_finance_baseline.json") == "69b2228e41a708fbba502dc87f089b546e215bef91a89df04c79987fbd78f2fb"


def test_final_freeze_manifest_records_all_twelve_pc6_results_without_tag():
    manifest=_json("pc6_release_manifest.json")
    assert manifest["neutral_proof"]["wbs"]==[f"PC6.{number}" for number in range(1,13)]
    assert all(value=="PASS" for value in manifest["neutral_proof"]["candidate_results"].values())
    assert manifest["commit"]==manifest["tag"]=="NOT_CREATED"
    assert manifest["operator_evidence"]["single_gate"]=="PENDING_OPERATOR_EXECUTION"
