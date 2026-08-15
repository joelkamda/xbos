from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform_admin/v1"


def j(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def canonical_sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def lineage() -> list[str]:
    revisions = {}
    for path in (ROOT / "alembic_neutral/versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        try: values[target.id] = ast.literal_eval(node.value)
                        except Exception: pass
        if isinstance(values.get("revision"), str): revisions[values["revision"]] = values.get("down_revision")
    parents = {v for v in revisions.values() if isinstance(v, str)}
    heads = list(set(revisions) - parents)
    assert len(heads) == 1
    out=[]; current=heads[0]
    while current:
        out.append(current); current=revisions[current]
    return list(reversed(out))


def test_pa6_is_pure_aggregate_freeze():
    a=j("pa6_aggregate_conformance_freeze.json")
    assert a["migration"] == "NONE"
    assert a["business_capability_change"] == "NONE"
    assert a["previous_head"] == a["accepted_head"] == "pa45_support_recovery_health_040"


def test_pa6_covers_pa0_through_pa6():
    assert j("pa6_aggregate_conformance_freeze.json")["coverage"] == [f"PA{i}" for i in range(7)]


def test_component_coverage_is_lossless():
    assert j("pa0123_authority.json")["coverage"] == ["PA0","PA1","PA2","PA3"]
    assert j("pa45_authority.json")["coverage"] == ["PA4","PA5"]


def test_constitution_is_shared_with_pa0123():
    assert j("pa6_aggregate_conformance_freeze.json")["constitutional_rule"] == j("pa0123_authority.json")["constitutional_rule"]


def test_platform_core_authorities_remain_external():
    b=j("pa0123_authority.json")["authority_boundaries"]
    assert (b["tenant_lifecycle"],b["effective_entitlement"],b["authorization_and_admin_identity"],b["template_and_pack_composition"]) == ("PC1","PC4","PC5","PK")


def test_pa45_reuses_security_and_pack_authority():
    b=j("pa45_authority.json")["authority_boundaries"]
    assert b["authorization_and_identity"] == "PC5_REUSED"
    assert b["template_composition"] == "PK_REUSED"
    assert b["health_snapshot"] == "PA45_DERIVED_EVIDENCE"


def test_finance_so_and_pk_remain_unchanged():
    a=j("pa6_aggregate_conformance_freeze.json")
    inv=a["aggregate_invariants"]
    assert inv["finance"] == inv["shared_operations"] == inv["pack_platform"] == "UNCHANGED"


def test_health_remains_observation_not_source_truth():
    assert "health is observation, never source truth" in j("pa45_health_contract.json")["laws"]


def test_full_merchant_journey_is_explicit():
    journey=j("pa6_aggregate_conformance_freeze.json")["full_merchant_journey"]
    assert journey[0] == "merchant_registered"
    assert "usage_recorded_and_quota_evaluated" in journey
    assert "delegated_support_opened_and_evidenced" in journey
    assert journey[-1] == "support_session_closed"


def test_pa_migration_prefix_is_linear_and_descendant_safe():
    chain=lineage(); expected=["pk456_pack_conformance_templates_038","pa0123_merchant_lifecycle_subscriptions_onboarding_039","pa45_support_recovery_health_040"]
    start=chain.index(expected[0]); assert chain[start:start+3] == expected


def test_dependencies_are_canonical_lf_fingerprinted():
    a=j("pa6_aggregate_conformance_freeze.json")
    for name,expected in a["dependency_fingerprints"].items():
        assert canonical_sha(ROOT/name) == expected


def test_r0_handoff_is_explicit_and_preserves_all_frozen_layers():
    h=j("pa6_aggregate_conformance_freeze.json")["next_handoff"]
    assert h["status"] == "R0_READY_AFTER_OPERATOR_GATE"
    assert h["sequence"] == "R0-R5"
    assert len(h["must_preserve"]) == 6


def test_pa45_verifier_bootstraps_repository_root_for_standalone_execution():
    source = (ROOT / "scripts/verify_pa45_platform_support_recovery_health.py").read_text(encoding="utf-8")
    compact = source.replace(" ", "")
    assert "importsys" in compact
    assert "ifstr(ROOT)notinsys.path" in compact
    assert "sys.path.insert(0,str(ROOT))" in compact


def test_pa6_development_adoption_is_resumable_only_from_pa0123_or_pa45():
    source = (ROOT / "scripts/verify_pa6_platform_administration_aggregate_freeze.py").read_text(encoding="utf-8")
    assert "if dev_head == PA0123_HEAD:" in source
    assert 'development_action = "ADOPT_PA45"' in source
    assert 'elif dev_head != HEAD:' in source
    assert 'PA6_DEVELOPMENT_HEAD_UNSAFE=' in source
    assert 'PA6_DEVELOPMENT_ADOPTION_FAILED=' in source
