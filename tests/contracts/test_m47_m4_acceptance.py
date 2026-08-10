"""Contract tests for the M4 hardening and freeze boundary."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "contracts" / "finance" / "v1" / "m47_m4_acceptance_and_freeze.json"
MANIFEST = ROOT / "contracts" / "finance" / "v1" / "m4_release_manifest.json"
AUTHORITY = ROOT / "core" / "domain" / "finance" / "m4_acceptance.py"
VERIFIER = ROOT / "scripts" / "verify_m47_m4_acceptance.py"
M43_VERIFIER = ROOT / "scripts" / "verify_m43_payment_settlements.py"
M44_VERIFIER = ROOT / "scripts" / "verify_m44_payment_patterns.py"


def _semantic_hash(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def test_acceptance_contract_freezes_expected_checkpoint():
    contract = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    assert contract["contract"] == "XBOS_M47_M4_ACCEPTANCE_AND_FREEZE"
    assert contract["source_checkpoint"] == {
        "branch": "track-b/m4-payments-settlement-orchestration",
        "parent_commit": "ef8b097",
    }
    assert contract["canonical_head"] == "m46_provider_financials_015"
    assert contract["adds_migration"] is False


def test_release_manifest_has_all_seven_ordered_components():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["baseline_code"] == "XBOS_M4_PAYMENTS_SETTLEMENT_ORCHESTRATION_RELEASE"
    assert [item["milestone"] for item in manifest["components"]] == [f"M4.{index}" for index in range(7)]
    assert [item["sequence"] for item in manifest["components"]] == list(range(1, 8))


def test_every_manifest_semantic_fingerprint_matches():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for component in manifest["components"]:
        assert _semantic_hash(ROOT / component["path"]) == component["semantic_sha256"]


def test_release_tag_is_fixed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["release_tag"] == "track-b-m4-payments-settlement-orchestration-20260810"


def test_m47_adds_no_migration():
    assert not tuple((ROOT / "alembic_neutral" / "versions").glob("m47_*.py"))
    assert "unexpected_m4_closure_migration" in AUTHORITY.read_text(encoding="utf-8")


def test_acceptance_authority_parses_migrations_without_importing_them():
    source = AUTHORITY.read_text(encoding="utf-8")
    assert "ast.parse" in source
    assert "ast.literal_eval" in source
    assert "len(heads) != 1" in source
    ast.parse(source)


def test_frozen_lineage_ends_at_m46():
    tree = ast.parse(AUTHORITY.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "EXPECTED_LINEAGE" for target in node.targets))
    lineage = ast.literal_eval(assignment.value)
    assert lineage[-6:] == (
        "m34_obligation_aging_010", "m40_payment_foundation_011", "m42_payment_attempts_012",
        "m43_payment_settlements_013", "m44_payment_patterns_014", "m46_provider_financials_015",
    )


@pytest.mark.parametrize("token", [
    "verify_m40_payment_foundation as m40",
    "verify_m41_payment_commands as m41",
    "verify_m42_payment_attempts as m42",
    "verify_m43_payment_settlements as m43",
    "verify_m44_payment_patterns as m44",
    "verify_m45_xafpay_orchestration as m45",
    "verify_m46_provider_financials as m46",
])
def test_aggregate_verifier_loads_every_capability(token):
    assert token in VERIFIER.read_text(encoding="utf-8")


def test_historical_capabilities_run_on_clean_current_head_clones():
    source = VERIFIER.read_text(encoding="utf-8")
    assert "_run_current_head_capability" in source
    assert 'TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"' in source
    assert "disposable clone revision differs" in source


def test_m40_retains_real_upgrade_downgrade_upgrade_rehearsal():
    source = VERIFIER.read_text(encoding="utf-8")
    assert '_migrate(M40_DATABASE, "m40_payment_foundation_011")' in source
    assert '_migrate(M40_DATABASE, "m34_obligation_aging_010", downgrade=True)' in source
    assert "m40._verify_foundation" in source


def test_provider_outage_fails_closed():
    source = VERIFIER.read_text(encoding="utf-8")
    assert "class _OutageTransport" in source
    assert 'raise TimeoutError("simulated provider outage")' in source
    assert "provider outage fabricated a successful initiation" in source


def test_callback_security_is_exercised_not_reimplemented():
    source = VERIFIER.read_text(encoding="utf-8")
    assert "(M45_DATABASE, m45._exercise)" in source
    historical = (ROOT / "scripts" / "verify_m45_xafpay_orchestration.py").read_text(encoding="utf-8")
    for marker in ("callback replay failed", "callback_replay_conflict", "invalid signature was accepted", "cross-tenant callback was accepted"):
        assert marker in historical


def test_mixed_tender_and_offline_cash_are_exercised():
    source = (ROOT / "scripts" / "verify_m44_payment_patterns.py").read_text(encoding="utf-8")
    assert 'mixed=_intent' in source
    assert 'cash_set=_settlement' in source
    assert 'cash=PASS' in source and 'split_tender=PASS' in source


def test_development_gate_is_exact_and_read_only():
    source = VERIFIER.read_text(encoding="utf-8")
    assert 'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"' in source
    assert 'revision != EXPECTED_HEAD' in source
    assert 'catalog != 20' in source
    assert "development release tables are not empty" in source
    assert "INSERT INTO" not in source


def test_source_checkpoint_is_enforced_inside_python():
    source = VERIFIER.read_text(encoding="utf-8")
    assert 'branch != "track-b/m4-payments-settlement-orchestration"' in source
    assert 'commit != "ef8b097"' in source
    assert '["git", "diff", "--name-only"]' in source
    assert '"scripts/verify_m43_payment_settlements.py"' in source
    assert '"scripts/verify_m44_payment_patterns.py"' in source


def test_m43_value_date_check_is_independent_of_wall_clock_date():
    source = M43_VERIFIER.read_text(encoding="utf-8")
    assert 'row["value_date"]!=date(2026,8,10)' in source
    assert 'row["recorded_date"] is None' in source
    assert 'row["value_date"]==row["recorded_date"]' not in source


def test_m44_delayed_settlement_check_is_independent_of_wall_clock_date():
    source = M44_VERIFIER.read_text(encoding="utf-8")
    assert 'dates[0]!=date(2026,8,10)' in source
    assert 'dates[1] is None' in source
    assert 'dates[0]==dates[1]' not in source


def test_final_token_names_every_exit_gate():
    source = VERIFIER.read_text(encoding="utf-8")
    for token in (
        "callback_replay=PASS", "callback_conflict=PASS", "provider_outage=PASS",
        "mixed_tender=PASS", "offline_cash=PASS", "security=PASS",
        "tenant_isolation=PASS", "disposable_databases_dropped=true",
    ):
        assert token in source
