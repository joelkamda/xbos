import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_PATH = ROOT / "contracts" / "persistence" / "v1" / "migration_authority.json"


@pytest.fixture(scope="module")
def authority() -> dict:
    with AUTHORITY_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def _revision_value(path: Path, field: str):
    source = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^{field}(?:\s*:[^=]+)?\s*=\s*(None|['\"]([^'\"]+)['\"])",
        source,
        re.MULTILINE,
    )
    assert match, f"Missing {field} in {path.name}"
    return None if match.group(1) == "None" else match.group(2)


def test_authority_identity_is_approved_v1(authority):
    assert authority["contract_code"] == "XBOS_M1_PERSISTENCE_MIGRATION_AUTHORITY"
    assert authority["contract_version"] == 1
    assert authority["contract_revision"] == 1
    assert authority["status"] == "approved"


def test_authority_starts_from_the_approved_m0_baseline(authority):
    assert authority["source_baseline"] == {
        "branch": "track-b/m1-canonical-persistence-foundation",
        "tag": "track-b-m0-neutral-contracts-20260806",
        "commit": "1f047a5",
    }


def test_observed_topology_is_one_linear_transactional_head(authority):
    topology = authority["observed_migration_topology"]
    assert topology["root_revision"] == "86322f59e0de"
    assert topology["current_head"] == "5c706797029a"
    assert topology["head_count"] == 1
    assert topology["branch_count"] == 0
    assert topology["transactional_ddl"] is True


def test_revision_files_form_the_declared_linear_chain(authority):
    versions = ROOT / "alembic" / "versions"
    declared = authority["observed_migration_topology"]["ordered_revisions"]
    discovered = {}

    for path in versions.glob("*.py"):
        revision = _revision_value(path, "revision")
        down_revision = _revision_value(path, "down_revision")
        discovered[revision] = down_revision

    assert set(discovered) == set(declared)
    assert discovered[declared[0]] is None
    for parent, child in zip(declared, declared[1:]):
        assert discovered[child] == parent


def test_environment_database_url_has_highest_precedence(tmp_path):
    from core.persistence.database_config import resolve_database_url

    env_file = tmp_path / "environment"
    env_file.write_text(
        "DATABASE_URL=postgresql://file@localhost/file_db\n",
        encoding="utf-8",
    )
    result = resolve_database_url(
        configured_url="postgresql://config@localhost/config_db",
        environ={"DATABASE_URL": "postgresql://process@localhost/process_db"},
        env_file=env_file,
    )
    assert result == "postgresql://process@localhost/process_db"


def test_environment_file_supports_quotes_and_export(tmp_path):
    from core.persistence.database_config import resolve_database_url

    env_file = tmp_path / "environment"
    env_file.write_text(
        "# local configuration\n"
        "export DATABASE_URL='postgresql+psycopg2://user:p%40ss@localhost/file_db'\n",
        encoding="utf-8",
    )
    result = resolve_database_url(environ={}, env_file=env_file)
    assert result.endswith("@localhost/file_db")


def test_explicit_configuration_is_the_last_fallback(tmp_path):
    from core.persistence.database_config import resolve_database_url

    result = resolve_database_url(
        configured_url="postgresql://config@localhost/config_db",
        environ={},
        env_file=tmp_path / "missing",
    )
    assert result == "postgresql://config@localhost/config_db"


def test_missing_database_url_fails_closed(tmp_path):
    from core.persistence.database_config import (
        DatabaseConfigurationError,
        resolve_database_url,
    )

    try:
        resolve_database_url(environ={}, env_file=tmp_path / "missing")
    except DatabaseConfigurationError as exc:
        assert "DATABASE_URL is required" in str(exc)
    else:
        raise AssertionError("Missing database configuration did not fail closed")


def test_non_postgresql_database_url_is_rejected(tmp_path):
    from core.persistence.database_config import (
        DatabaseConfigurationError,
        resolve_database_url,
    )

    try:
        resolve_database_url(
            configured_url="sqlite:///unsafe.db",
            environ={},
            env_file=tmp_path / "missing",
        )
    except DatabaseConfigurationError as exc:
        assert "requires PostgreSQL" in str(exc)
    else:
        raise AssertionError("Non-PostgreSQL configuration was accepted")


def test_database_url_must_name_a_database(tmp_path):
    from core.persistence.database_config import (
        DatabaseConfigurationError,
        resolve_database_url,
    )

    try:
        resolve_database_url(
            configured_url="postgresql://user@localhost",
            environ={},
            env_file=tmp_path / "missing",
        )
    except DatabaseConfigurationError as exc:
        assert "must name a database" in str(exc)
    else:
        raise AssertionError("Database-less PostgreSQL URL was accepted")


def test_database_module_contains_no_literal_postgresql_url():
    source = (ROOT / "database.py").read_text(encoding="utf-8")
    assert "postgresql://" not in source
    assert "postgresql+psycopg2://" not in source
    assert "resolve_database_url()" in source


def test_application_and_alembic_use_the_same_resolver():
    database_source = (ROOT / "database.py").read_text(encoding="utf-8")
    alembic_source = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    authority = "core.persistence.database_config import resolve_database_url"
    assert authority in database_source
    assert authority in alembic_source


def test_metadata_naming_convention_matches_authority(authority):
    from core.persistence.metadata import NAMING_CONVENTION

    assert NAMING_CONVENTION == authority["metadata_authority"]["naming_convention"]
    assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}


def test_declarative_base_uses_the_authoritative_metadata():
    from core.persistence.metadata import metadata
    from database import Base

    assert Base.metadata is metadata
    assert Base.metadata.naming_convention is not None


def test_model_registration_matches_the_declared_module_inventory(authority):
    from core.models_import import MODEL_MODULES

    assert list(MODEL_MODULES) == authority["model_registration"]["modules"]
    assert len(MODEL_MODULES) == len(set(MODEL_MODULES)) == 10


def test_duplicate_catalog_inventory_models_are_excluded(authority):
    from core.models_import import EXCLUDED_DUPLICATE_MODEL_MODULES, MODEL_MODULES

    excluded = authority["model_registration"]["excluded_duplicate_modules"]
    assert list(EXCLUDED_DUPLICATE_MODEL_MODULES) == excluded
    assert set(EXCLUDED_DUPLICATE_MODEL_MODULES).isdisjoint(MODEL_MODULES)
    assert authority["model_registration"]["duplicate_owner_decision"] == {
        "inventory_items": "core.domain.inventory.models",
        "inventory_movements": "core.domain.inventory.models",
    }


def test_registered_metadata_contains_the_observed_financial_spine():
    import core.models_import  # noqa: F401
    from database import Base

    expected = {
        "tenants",
        "branches",
        "users",
        "roles",
        "taxonomy_nodes",
        "atomic_units",
        "atomic_unit_taxonomy",
        "orders",
        "order_items",
        "order_item_modifiers",
        "sales",
        "sale_items",
        "payments",
        "payment_intents",
        "payment_attempts",
        "inventory_items",
        "inventory_movements",
        "treasury_logs",
        "recon_sheets",
        "accounts_receivable",
        "accounts_receivable_repayments",
    }
    assert expected <= set(Base.metadata.tables)


def test_registered_table_names_are_unique():
    import core.models_import  # noqa: F401
    from database import Base

    names = [table.name for table in Base.metadata.sorted_tables]
    assert len(names) == len(set(names))


def test_alembic_uses_direct_resolved_engine_not_config_engine():
    source = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "engine_from_config" not in source
    assert "create_engine(" in source
    assert "MIGRATION_DATABASE_URL" in source


def test_alembic_drift_comparison_and_transaction_options_are_explicit(authority):
    source = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    alembic = authority["alembic_authority"]
    assert alembic["compare_type"] is True
    assert alembic["compare_server_default"] is True
    assert alembic["include_schemas"] is False
    assert alembic["transaction_per_migration"] is True
    for option in (
        '"compare_type": True',
        '"compare_server_default": True',
        '"include_schemas": False',
        '"transaction_per_migration": True',
    ):
        assert option in source


def test_new_migration_parent_and_autogenerate_policy_are_fixed(authority):
    alembic = authority["alembic_authority"]
    assert alembic["new_revision_parent"] == "5c706797029a"
    assert alembic["historical_revisions_are_immutable"] is True
    assert alembic["autogenerate_policy"] == "review_only_never_auto_apply"
    assert alembic["autogenerate_blocked_until_metadata_drift_is_audited"] is True


def test_fresh_database_gap_is_visible_and_blocks_m1_release(authority):
    gap = authority["fresh_database_gap"]
    assert gap["status"] == "open_release_blocker"
    assert gap["historical_revision_rewrite_allowed"] is False
    assert gap["full_empty_database_upgrade_currently_supported"] is False
    assert gap["slice_one_parity_development_allowed"] is True
    assert gap["parity_precondition_revision"] == "5c706797029a"


def test_automated_database_mutation_is_restricted(authority):
    safety = authority["automated_database_safety"]
    assert safety["mutable_database_names"] == ["xbos_track_b_test"]
    assert safety["mutable_database_prefixes"] == ["xbos_migration_test_"]
    assert safety["parity_source_is_read_only"] is True
    assert safety["production_migration_allowed"] is False


def test_slice_one_scope_is_exact_and_additive(authority):
    expected = {
        "organization_units",
        "currency_assets",
        "tenant_currency_policies",
        "business_cycle_policies",
        "kernel_source_records",
        "financial_counterparties",
        "operational_financial_accounts",
        "payment_provider_accounts",
        "idempotency_records",
        "outbox_messages",
        "document_sequences",
    }
    assert set(authority["slice_one_scope"]) == expected
    assert authority["alembic_authority"]["new_objects_are_additive"] is True
    assert authority["alembic_authority"]["destructive_legacy_cutover_allowed"] is False


def test_m1_0_exit_gate_preserves_visible_safety_blockers(authority):
    gate = authority["m1_0_exit_gate"]
    assert len(gate) == len(set(gate)) == 9
    assert "alembic_head_remains_5c706797029a" in gate
    assert "autogenerate_remains_blocked_pending_drift_audit" in gate
    assert "fresh_database_gap_is_visible_and_blocks_m1_release" in gate
