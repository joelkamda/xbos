import json
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from core.persistence.m14_authority import (
    ACTIVATION_DATABASE,
    ACTIVE_SCRIPT_LOCATION,
    CANONICAL_HEAD_REVISION,
    FOUNDATION_TABLES,
    SAFE_INI_URL,
    SOURCE_AUTHORITY_REVISION,
    SOURCE_STATE_REVISION,
    assert_exact_source_schema,
    checked_activation_url,
    source_tables_from_baseline,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "persistence" / "v1" / "m14_canonical_migration_authority.json"
ALEMBIC_INI = ROOT / "alembic.ini"
BASELINE = ROOT / "alembic_reconstruction" / "sql" / "source_state_baseline.sql"
ACTIVATOR = ROOT / "scripts" / "activate_canonical_migration_authority.py"


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _ini_value(name: str) -> str:
    prefix = f"{name} ="
    matches = [
        line.split("=", 1)[1].strip()
        for line in ALEMBIC_INI.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(prefix)
    ]
    assert len(matches) == 1
    return matches[0]


def test_main_alembic_configuration_is_the_canonical_authority():
    assert _ini_value("script_location") == ACTIVE_SCRIPT_LOCATION
    assert _ini_value("sqlalchemy.url") == SAFE_INI_URL


def test_main_alembic_configuration_contains_no_database_credentials():
    value = _ini_value("sqlalchemy.url")
    assert "postgres" not in value
    assert "@" not in value
    assert "://" in value


def test_contract_and_policy_revision_chain_agree():
    contract = _contract()
    assert contract["canonical_head"] == CANONICAL_HEAD_REVISION
    assert contract["source_state_revision"] == SOURCE_STATE_REVISION
    assert contract["recognized_source_authority_revision"] == SOURCE_AUTHORITY_REVISION


def test_one_lineage_has_one_active_configuration():
    contract = _contract()
    assert contract["active_configuration"] == "alembic.ini"
    assert contract["active_script_location"] == ACTIVE_SCRIPT_LOCATION
    assert contract["authority_disposition"]["alembic_neutral"] == "sole_active_lineage"


def test_source_and_reconstruction_directories_are_evidence_not_authority():
    disposition = _contract()["authority_disposition"]
    assert disposition["alembic"] == "inactive_source_history_evidence"
    assert disposition["alembic_reconstruction"] == "inactive_reconstruction_evidence"


def test_activation_does_not_enable_financial_runtime_changes():
    scope = _contract()["activation_scope"]
    assert scope["canonical_event_writes"] is False
    assert scope["event_catalog_seed"] is False
    assert scope["historical_transformation"] is False
    assert scope["application_writer_cutover"] is False


def test_activation_is_not_a_production_or_parity_operation():
    scope = _contract()["activation_scope"]
    assert scope["database"] == ACTIVATION_DATABASE
    assert scope["host"] == "local_only"
    assert scope["production_activation"] is False
    assert scope["parity_activation"] is False


def test_url_guard_accepts_only_the_exact_local_development_database():
    accepted = checked_activation_url(
        make_url(
            f"postgresql+psycopg2://postgres:password@localhost:5432/{ACTIVATION_DATABASE}"
        )
    )
    assert accepted.database == ACTIVATION_DATABASE

    with pytest.raises(RuntimeError):
        checked_activation_url(
            "postgresql+psycopg2://postgres:password@localhost:5432/xbos"
        )
    with pytest.raises(RuntimeError):
        checked_activation_url(
            f"postgresql+psycopg2://postgres:password@db.example.com:5432/{ACTIVATION_DATABASE}"
        )


def test_source_baseline_has_a_stable_nonempty_table_inventory():
    tables = source_tables_from_baseline(BASELINE)
    assert "alembic_version" in tables
    assert "tenants" in tables
    assert "users" in tables
    assert "treasury_logs" in tables
    assert not (tables & FOUNDATION_TABLES)


def test_exact_source_schema_check_rejects_missing_or_extra_tables():
    expected = {"alembic_version", "tenants"}
    assert_exact_source_schema(expected, expected)
    with pytest.raises(RuntimeError):
        assert_exact_source_schema({"alembic_version"}, expected)
    with pytest.raises(RuntimeError):
        assert_exact_source_schema(expected | {"unexpected"}, expected)


def test_rollback_is_limited_to_an_empty_foundation():
    rollback = _contract()["rollback_before_use"]
    assert rollback["allowed"] is True
    assert rollback["requires_canonical_head"] is True
    assert rollback["requires_every_foundation_table_empty"] is True
    assert _contract()["post_use_correction"] == "forward_only"


def test_activator_requires_explicit_adoption_confirmations():
    source = ACTIVATOR.read_text(encoding="utf-8")
    assert "--confirm-database-name" in source
    assert "--confirm-source-revision" in source
    assert "--confirm-empty-foundation-rollback" in source
    assert "EMPTY-M14-FOUNDATION" in source


def test_activator_checks_foundation_emptiness_before_rollback():
    source = ACTIVATOR.read_text(encoding="utf-8")
    assert '_preflight() != "adopted_empty"' in source
    assert "command.downgrade" in source


def test_config_activation_edits_only_reviewed_authority_values():
    source = ACTIVATOR.read_text(encoding="utf-8")
    assert 're.subn(' in source
    assert 'script_location' in source
    assert r"sqlalchemy\.url" in source
    assert 'ALEMBIC_INI.write_text' in source


def test_foundation_inventory_matches_m13_contract():
    m13 = json.loads(
        (
            ROOT
            / "contracts"
            / "persistence"
            / "v1"
            / "m13_neutral_financial_foundation.json"
        ).read_text(encoding="utf-8")
    )
    assert FOUNDATION_TABLES == frozenset(m13["foundation_tables"])
