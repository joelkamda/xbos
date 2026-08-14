from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from scripts.verify_so_aggregate_conformance_freeze import (
    HEAD, PREVIOUS, SOURCE, EXPECTED_COMPONENT_HEADS, EXPECTED_OWNERS,
    _development_action, _verify_authority_graph, _verify_neutrality_and_pk_readiness,
    _verify_public_boundaries, _verify_tenant_idempotency,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/shared_operations/v1"


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_aggregate_contract_freezes_so0_through_so10_without_new_business_capability():
    contract = load("so_aggregate_conformance_freeze.json")
    assert contract["source_checkpoint"] == SOURCE
    assert contract["previous_head"] == PREVIOUS
    assert contract["accepted_head"] == HEAD
    assert contract["business_capability_change"] == "NONE"
    assert contract["migration"] == "CONFORMANCE_HARDENING_ONLY"
    assert [item["milestone"] for item in contract["components"]] == [f"SO{n}" for n in range(11)]
    assert contract["cutover"] == "NOT_AUTHORIZED"
    assert contract["writer_retirement"] == "NOT_EXECUTED"


def test_all_component_release_heads_form_the_accepted_shared_operations_lineage():
    for code, expected in EXPECTED_COMPONENT_HEADS.items():
        number = int(code[2:])
        manifest = load(f"so{number}_release_manifest.json")
        assert (manifest["previous_head"], manifest["accepted_head"]) == expected
    wrapper = (ROOT / "alembic_neutral/versions/so_aggregate_conformance_hardening_036.py").read_text(encoding="utf-8")
    assert f'revision="{HEAD}"' in wrapper
    assert f'down_revision="{PREVIOUS}"' in wrapper


def test_authority_graph_has_one_expected_owner_and_finance_stays_external():
    _verify_authority_graph()
    module_map = json.loads((ROOT / "contracts/platform/v1/pc0_module_map.json").read_text(encoding="utf-8"))
    by_code = {item["code"]: item for item in module_map["modules"]}
    for code, owner in EXPECTED_OWNERS.items():
        assert by_code[code]["owner"] == owner
    assert load("so10_authority.json")["financial_authority"] == "NEUTRAL_FINANCE_PRESERVED"


def test_cross_module_application_boundary_has_no_private_import_or_external_source_writer():
    _verify_public_boundaries()
    # The only direct cross-SO import is SO4 consuming SO3's public package.
    source = (ROOT / "shared_operations/so4/service.py").read_text(encoding="utf-8")
    assert "from shared_operations.so3 import MoveStock" in source
    assert "shared_operations.so3.sql_repository" not in source


def test_aggregate_hardening_makes_so2_idempotency_tenant_scoped_and_fail_closed():
    _verify_tenant_idempotency()
    up = (ROOT / "alembic_neutral/sql/so_aggregate_conformance_hardening_up.sql").read_text(encoding="utf-8")
    down = (ROOT / "alembic_neutral/sql/so_aggregate_conformance_hardening_down.sql").read_text(encoding="utf-8")
    assert "SO_AGG_SO2_COMMAND_TENANT_BACKFILL_REQUIRED" in up
    assert "UNIQUE(tenant_id,command_key)" in up
    assert "FOREIGN KEY(tenant_id,result_id)" in up
    assert "SO_AGG_DOWNGRADE_GLOBAL_COMMAND_KEY_CONFLICT" in down


def test_historical_so2_rehearsal_compatibility_is_preserved_while_aggregate_head_uses_tenant_scope():
    source = (ROOT / "shared_operations/so2/sql_repository.py").read_text(encoding="utf-8")
    assert "_tenant_scoped_commands" in source
    assert "Historical SO2 replay compatibility before aggregate hardening _036" in source
    assert "ON CONFLICT(tenant_id,command_key)" in source
    assert "ON CONFLICT(command_key)" in source


def test_development_adoption_is_resumable_and_other_heads_fail_closed():
    assert _development_action(PREVIOUS) == "UPGRADE"
    assert _development_action(HEAD) == "VERIFY_IN_PLACE"
    with pytest.raises(RuntimeError, match="SO_AGG_DEVELOPMENT_HEAD_UNSAFE"):
        _development_action("parallel_head")


def test_all_so_modules_keep_two_neutral_profiles_and_no_active_industry_default():
    _verify_neutrality_and_pk_readiness()


def test_aggregate_acceptance_uses_real_template0_replay_reversibility_and_cross_tenant_database_proof():
    source = (ROOT / "scripts/verify_so_aggregate_conformance_freeze.py").read_text(encoding="utf-8")
    for marker in (
        "TEMPLATE template0",
        "_run(command.upgrade, cfg, rendered, PREVIOUS)",
        "_run(command.upgrade, cfg, rendered, HEAD)",
        "_run(command.downgrade, cfg, rendered, PREVIOUS)",
        "aggregate-shared-command-key",
        "SO_AGG_CROSS_TENANT_RESULT_FK",
        "finance_after != finance_before",
        "SO_AGG_DEVELOPMENT_DATA_MUTATION",
    ):
        assert marker in source


def test_aggregate_release_manifest_and_operator_gate_exist():
    manifest = load("so_aggregate_release_manifest.json")
    paths = [item["path"] for item in manifest["artifacts"]]
    assert len(paths) == len(set(paths))
    assert "XBOS_SO_AGG_RUN_ACCEPTANCE.cmd" in paths
    assert "scripts/verify_so_aggregate_conformance_freeze.py" in paths
    assert "tests/contracts/test_so_aggregate_conformance_freeze.py" in paths
    assert (ROOT / "SO_AGG_INSTALL_MANIFEST.txt").is_file()
    assert (ROOT / "XBOS_SO_AGG_INSTALL_AND_VERIFY.txt").is_file()
