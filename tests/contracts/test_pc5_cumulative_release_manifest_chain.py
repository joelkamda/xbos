"""Canonical source and cumulative PC0→PC5 release-integrity regression."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from core.platform.release_integrity import (
    canonical_bytes,
    canonical_sha256,
    fingerprint_policy,
    latest_release,
    verify_historical_release,
    verify_latest_release,
)

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/platform/v1"


def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))


def test_every_historical_release_resolves_exactly_through_latest_descendant():
    current,_=latest_release(ROOT)
    reports=[verify_historical_release(ROOT,number) for number in range(1,current)]
    assert [x["latest"] for x in reports]==[current]*(current-1)
    assert all(x["replacement_count"]>0 for x in reports)


def test_latest_manifest_exactly_fingerprints_canonical_current_sources():
    number,manifest=latest_release(ROOT)
    assert number>=5 and verify_latest_release(ROOT)["artifact_count"]==len(manifest["artifacts"])
    policy=fingerprint_policy(manifest)
    assert policy["text_normalization"]=="crlf_to_lf_only" and policy["binary_normalization"]=="exact_bytes"


def test_canonical_lf_and_git_equivalent_windows_crlf_match():
    lf=b"first line\nsecond line\n"
    crlf=b"first line\r\nsecond line\r\n"
    assert canonical_bytes(lf,artifact_kind="text")==canonical_bytes(crlf,artifact_kind="text")==lf
    assert hashlib.sha256(canonical_bytes(lf,artifact_kind="text")).hexdigest()==hashlib.sha256(canonical_bytes(crlf,artifact_kind="text")).hexdigest()


def test_clean_git_crlf_checkout_uses_blob_but_dirty_mutation_uses_worktree(tmp_path):
    def git(*args):return subprocess.run(["git","-C",str(tmp_path),*args],check=True,capture_output=True)
    git("init","-q");git("config","user.email","pc5@example.invalid");git("config","user.name","PC5 Test")
    (tmp_path/".gitattributes").write_text("*.py text eol=crlf\n",encoding="utf-8")
    source=tmp_path/"authority.py";source.write_bytes(b"authority = 'pc5'\n")
    git("add",".gitattributes","authority.py");git("commit","-q","-m","fixture");source.unlink();git("checkout-index","authority.py")
    assert b"\r\n" in source.read_bytes() and git("diff","--quiet","--","authority.py").returncode==0
    expected=hashlib.sha256(b"authority = 'pc5'\n").hexdigest()
    assert canonical_sha256(source,relative_path="authority.py",repository_root=tmp_path)==expected
    source.write_bytes(b"authority = 'pc6'\r\n")
    dirty=subprocess.run(["git","-C",str(tmp_path),"diff","--quiet","--","authority.py"],check=False).returncode
    assert dirty!=0
    assert canonical_sha256(source,relative_path="authority.py",repository_root=tmp_path)!=expected


def test_real_character_and_unauthorized_whitespace_mutations_fail():
    original=b"authority = 'pc5'\n"
    canonical=hashlib.sha256(canonical_bytes(original,artifact_kind="text")).hexdigest()
    one_character=b"authority = 'pc6'\n"
    added_space=b"authority  = 'pc5'\n"
    assert hashlib.sha256(canonical_bytes(one_character,artifact_kind="text")).hexdigest()!=canonical
    assert hashlib.sha256(canonical_bytes(added_space,artifact_kind="text")).hexdigest()!=canonical


def test_binary_artifacts_are_exact_and_binary_mutation_fails():
    original=b"\x00\r\n\xffpayload"
    assert canonical_bytes(original,artifact_kind="binary")==original
    assert hashlib.sha256(canonical_bytes(original+b"\x00",artifact_kind="binary")).hexdigest()!=hashlib.sha256(original).hexdigest()


def test_pc4_historical_hash_is_preserved_and_latest_replacement_is_canonical():
    path="core/platform/operating_context/__init__.py"
    pc4={x["path"]:x["sha256"] for x in _json("pc4_release_manifest.json")["artifacts"]}
    pc5={x["path"]:x for x in _json("pc5_release_manifest.json")["historical_pc4_replacements"]}
    assert pc4[path]=="ed960bb975c396653248002985210ed81169c6258e389566817b7bf74c2e3b5c"
    assert pc5[path]["historical_sha256"]==pc4[path]
    assert pc5[path]["descendant_sha256"]==canonical_sha256(ROOT/path,relative_path=path,repository_root=ROOT)


def test_pc5_sql_wrapper_and_release_metadata_mutations_fail():
    _,latest=latest_release(ROOT)
    historical={x["path"]:x["sha256"] for x in _json("pc5_release_manifest.json")["artifacts"]}
    replacements={x["path"]:x["descendant_sha256"] for x in latest["historical_pc5_replacements"]}
    for path in ("alembic_neutral/sql/pc5_identity_policy_audit_up.sql","alembic_neutral/versions/pc5_identity_policy_audit_025_canonical_security_authority.py","contracts/platform/v1/pc0_frozen_finance_inventory.json"):
        mutated=canonical_bytes((ROOT/path).read_bytes()+b"unauthorized",artifact_kind="text")
        assert hashlib.sha256(mutated).hexdigest()!=replacements.get(path,historical[path])


def test_frozen_finance_baseline_content_and_heads_remain_immutable():
    baseline=_json("pc0_frozen_finance_baseline.json")
    assert canonical_sha256(CONTRACTS/"pc0_frozen_finance_baseline.json",relative_path="contracts/platform/v1/pc0_frozen_finance_baseline.json")=="69b2228e41a708fbba502dc87f089b546e215bef91a89df04c79987fbd78f2fb"
    assert baseline["lineage"][-1]==baseline["canonical_head"]=="m64_reconciliation_controls_020"
    assert [_json(f"pc{x}_release_manifest.json")["accepted_head"] for x in range(1,6)]==["pc1_structural_context_021","pc2_party_authority_022","pc3_semantic_authority_023","pc4_operating_context_024","pc5_identity_policy_audit_025"]
