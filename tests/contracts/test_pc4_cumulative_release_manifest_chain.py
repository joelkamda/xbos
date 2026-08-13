"""Regression proof for exact cumulative Platform Core descendant fingerprints."""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/platform/v1"

def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _accepted(actual,historical,replacement):
    return actual==historical or bool(replacement and replacement.get("historical_sha256")==historical and replacement.get("descendant_sha256")==actual)

def test_every_transitive_pc1_pc2_pc3_mismatch_has_one_exact_pc4_replacement():
    pc4=_json("pc4_release_manifest.json")
    for number in (1,2,3):
        historical=_json(f"pc{number}_release_manifest.json")
        replacements={x["path"]:x for x in pc4[f"historical_pc{number}_replacements"]}
        for artifact in historical["artifacts"]:
            actual=_sha(ROOT/artifact["path"])
            assert _accepted(actual,artifact["sha256"],replacements.get(artifact["path"])),f"PC{number}:{artifact['path']}"
        assert set(replacements)=={a["path"] for a in historical["artifacts"] if _sha(ROOT/a["path"])!=a["sha256"]}

def test_pc4_manifest_exactly_fingerprints_every_current_release_artifact():
    manifest=_json("pc4_release_manifest.json")
    assert all(_sha(ROOT/item["path"])==item["sha256"] for item in manifest["artifacts"])

def test_corrected_pc4_sql_is_the_exact_pc0_authorized_descendant_byte_set():
    sql_path="alembic_neutral/sql/pc4_operating_context_up.sql"
    actual=_sha(ROOT/sql_path)
    inventory=_json("pc0_frozen_finance_inventory.json")
    extension=next(x for x in inventory["authorized_non_finance_extensions"] if f'{x["root"]}/{x["path"]}'==sql_path)
    assert extension["sha256"]==actual
    assert "OR NOT (CASE d.value_type" in (ROOT/sql_path).read_text(encoding="utf-8")
    assert "OR NOT CASE d.value_type" not in (ROOT/sql_path).read_text(encoding="utf-8")
    pc0=_json("pc0_release_manifest.json")
    inventory_artifact=next(x for x in pc0["artifacts"] if x["path"]=="contracts/platform/v1/pc0_frozen_finance_inventory.json")
    assert inventory_artifact["sha256"]==_sha(CONTRACTS/"pc0_frozen_finance_inventory.json")

def test_pc4_sql_and_alembic_wrapper_arbitrary_mutations_fail_exact_release_hashes():
    artifacts={x["path"]:x["sha256"] for x in _json("pc4_release_manifest.json")["artifacts"]}
    for relative in (
        "alembic_neutral/sql/pc4_operating_context_up.sql",
        "alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py",
    ):
        real=(ROOT/relative).read_bytes()
        assert _sha(ROOT/relative)==artifacts[relative]
        assert hashlib.sha256(real+b"unauthorized-byte").hexdigest()!=artifacts[relative]

def test_arbitrary_byte_mutation_is_not_accepted_by_historical_or_descendant_hash():
    pc1=_json("pc1_release_manifest.json");pc4=_json("pc4_release_manifest.json")
    artifact=next(x for x in pc1["artifacts"] if x["path"]=="contracts/platform/v1/pc0_frozen_finance_inventory.json")
    replacement=next(x for x in pc4["historical_pc1_replacements"] if x["path"]==artifact["path"])
    real=(ROOT/artifact["path"]).read_bytes();mutated=hashlib.sha256(real+b"unauthorized-byte").hexdigest()
    assert not _accepted(mutated,artifact["sha256"],replacement)

def test_frozen_finance_baseline_and_historical_heads_remain_immutable():
    baseline=_json("pc0_frozen_finance_baseline.json")
    assert baseline["canonical_head"]=="m64_reconciliation_controls_020"
    assert _sha(CONTRACTS/"pc0_frozen_finance_baseline.json")=="69b2228e41a708fbba502dc87f089b546e215bef91a89df04c79987fbd78f2fb"
    assert _json("pc1_release_manifest.json")["accepted_head"]=="pc1_structural_context_021"
    assert _json("pc2_release_manifest.json")["accepted_head"]=="pc2_party_authority_022"
    assert _json("pc3_release_manifest.json")["accepted_head"]=="pc3_semantic_authority_023"
    assert _json("pc4_release_manifest.json")["accepted_head"]=="pc4_operating_context_024"

def test_historical_lineage_is_exact_prefix_and_repairs_are_carried_forward():
    finance=_json("pc0_frozen_finance_baseline.json");expected=finance["lineage"]
    descendants=["pc1_structural_context_021","pc2_party_authority_022","pc3_semantic_authority_023","pc4_operating_context_024"]
    assert expected[-1]==finance["canonical_head"] and len(expected)==20
    assert (expected+descendants)[:len(expected)]==expected
    pc1=(ROOT/"scripts/verify_pc1_structural_authority.py").read_text();pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text();pc4version=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    assert "authority object types collapsed" not in pc1
    assert "name,semantic_level,taxonomy_type,sort_order" in pc3 and "'Child','domain','COMMERCE'" in pc3
    assert ".connection.cursor()" in pc4version and "exec_driver_sql" not in pc4version

def test_descendant_verifiers_prefer_pc4_exact_replacement_proofs():
    pc1=(ROOT/"scripts/verify_pc1_structural_authority.py").read_text();pc2=(ROOT/"scripts/verify_pc2_party_authority.py").read_text();pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text()
    assert '("pc4_release_manifest.json", "pc3_release_manifest.json", "pc2_release_manifest.json")' in pc1
    assert '("pc4_release_manifest.json","pc3_release_manifest.json")' in pc2
    assert 'historical_pc3_replacements' in pc3
