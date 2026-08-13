"""Historical PC4 proof under an authorized later Platform Core descendant."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.platform.release_integrity import (
    ReleaseIntegrityError,
    canonical_bytes,
    canonical_sha256,
    release_chain,
    verify_historical_release,
)

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/platform/v1"


def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))


def test_pc1_pc2_pc3_to_pc4_historical_replacement_snapshots_remain_exact():
    pc4=_json("pc4_release_manifest.json")
    pc4_artifacts={x["path"]:x["sha256"] for x in pc4["artifacts"]}
    for number in (1,2,3):
        historical=_json(f"pc{number}_release_manifest.json")
        replacements={x["path"]:x for x in pc4[f"historical_pc{number}_replacements"]}
        expected={x["path"] for x in historical["artifacts"] if x["path"] in pc4_artifacts and x["sha256"]!=pc4_artifacts[x["path"]]}
        assert set(replacements)==expected
        for artifact in historical["artifacts"]:
            path=artifact["path"]
            if path in expected:
                assert replacements[path]=={"path":path,"historical_sha256":artifact["sha256"],"descendant_sha256":pc4_artifacts[path]}


def test_pc4_history_resolves_to_current_only_through_latest_authorized_descendant():
    report=verify_historical_release(ROOT,4)
    assert report["milestone"]==4 and report["latest"]==5 and report["replacement_count"]>0
    assert [number for number,_ in release_chain(ROOT)]==[1,2,3,4,5]


def test_pc4_manifest_and_historical_head_are_preserved():
    pc4=_json("pc4_release_manifest.json")
    assert pc4["accepted_head"]=="pc4_operating_context_024"
    assert pc4["previous_head"]=="pc3_semantic_authority_023"
    assert len(pc4["artifacts"])==29
    assert len({x["path"] for x in pc4["artifacts"]})==29
    assert all(len(x["sha256"])==64 for x in pc4["artifacts"])


def test_corrected_pc4_sql_remains_the_pc0_authorized_source():
    relative="alembic_neutral/sql/pc4_operating_context_up.sql"
    inventory=_json("pc0_frozen_finance_inventory.json")
    extension=next(x for x in inventory["authorized_non_finance_extensions"] if f'{x["root"]}/{x["path"]}'==relative)
    assert extension["sha256"]==canonical_sha256(ROOT/relative,relative_path=relative,repository_root=ROOT)
    source=(ROOT/relative).read_text(encoding="utf-8")
    assert "OR NOT (CASE d.value_type" in source and "OR NOT CASE d.value_type" not in source


def test_pc4_sql_and_wrapper_arbitrary_mutations_are_rejected():
    latest=_json("pc5_release_manifest.json")
    replacements={x["path"]:x for x in latest["historical_pc4_replacements"]}
    for relative in ("alembic_neutral/sql/pc4_operating_context_up.sql","alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py"):
        mutation=hashlib.sha256(canonical_bytes((ROOT/relative).read_bytes()+b"unauthorized",artifact_kind="text")).hexdigest()
        expected=replacements.get(relative,{}).get("descendant_sha256") or next(x["sha256"] for x in _json("pc4_release_manifest.json")["artifacts"] if x["path"]==relative)
        assert mutation!=expected


def test_pc4_frozen_finance_and_historical_lineage_remain_immutable():
    baseline=_json("pc0_frozen_finance_baseline.json")
    assert baseline["canonical_head"]=="m64_reconciliation_controls_020"
    assert canonical_sha256(CONTRACTS/"pc0_frozen_finance_baseline.json",relative_path="contracts/platform/v1/pc0_frozen_finance_baseline.json")=="69b2228e41a708fbba502dc87f089b546e215bef91a89df04c79987fbd78f2fb"
    assert baseline["lineage"][-1]==baseline["canonical_head"] and len(baseline["lineage"])==20


def test_descendant_resolution_is_behavioral_and_unknown_chain_fails(tmp_path):
    directory=tmp_path/"contracts/platform/v1";directory.mkdir(parents=True)
    for number in range(1,6):(directory/f"pc{number}_release_manifest.json").write_bytes((CONTRACTS/f"pc{number}_release_manifest.json").read_bytes())
    assert [number for number,_ in release_chain(tmp_path)]==[1,2,3,4,5]
    (directory/"pc6_release_manifest.json").write_text(json.dumps({"previous_head":"unknown","accepted_head":"pc6_unknown"}),encoding="utf-8")
    with pytest.raises(ReleaseIntegrityError,match="unauthorized descendant lineage"):release_chain(tmp_path)


def test_pc3_fixture_and_pc4_wrapper_repairs_remain_present():
    pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text();wrapper=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    assert "name,semantic_level,taxonomy_type,sort_order" in pc3 and "'Child','domain','COMMERCE'" in pc3
    assert ".connection.cursor()" in wrapper and "exec_driver_sql" not in wrapper
