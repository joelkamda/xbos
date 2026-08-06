import ast
from hashlib import sha256
import json
from pathlib import Path

import pytest

from core.persistence.reconstruction_policy import (
    LOCAL_DATABASE_HOSTS,
    RECONSTRUCTION_DATABASE_NAME,
    RECONSTRUCTION_REVISION,
    UnsafeReconstructionTarget,
    validate_reconstruction_url,
)


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT / "contracts" / "persistence" / "v1" / "reconstruction_baseline.json"
)
SQL_PATH = ROOT / "alembic_reconstruction" / "sql" / "source_state_baseline.sql"
MIGRATION_PATH = (
    ROOT
    / "alembic_reconstruction"
    / "versions"
    / "m12_source_state_001_source_state_baseline.py"
)
RECONSTRUCTION_CONFIG_PATH = ROOT / "alembic_reconstruction.ini"
RECONSTRUCTION_ENV_PATH = ROOT / "alembic_reconstruction" / "env.py"
MAIN_CONFIG_PATH = ROOT / "alembic.ini"
RUNNER_PATH = ROOT / "scripts" / "verify_fresh_database_reconstruction.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline_sql():
    return SQL_PATH.read_text(encoding="utf-8")


def _table_names(sql):
    prefix = "CREATE TABLE public."
    return {
        line[len(prefix) :].split(" ", 1)[0]
        for line in sql.splitlines()
        if line.startswith(prefix)
    }


def test_contract_identity_is_candidate_not_active(contract):
    assert contract["contract_code"] == "XBOS_M1_2_RECONSTRUCTION_BASELINE"
    assert contract["contract_version"] == 2
    assert contract["status"] == "candidate_not_active"


def test_contract_is_anchored_to_m1_1(contract):
    assert contract["source_commit"] == "2f6cedb"
    assert contract["active_source_revision"] == "5c706797029a"
    assert contract["candidate_revision"] == RECONSTRUCTION_REVISION


def test_source_schema_checksum_is_frozen(contract):
    assert contract["source_schema"]["sha256"] == (
        "db109eb0a6f8c508fe235dc3635407f91bd2c71e41505a5820be3af82107d09f"
    )


def test_baseline_sql_checksum_is_frozen(contract, baseline_sql):
    actual = sha256(baseline_sql.encode("utf-8")).hexdigest()

    assert actual == contract["baseline_sql"]["sha256"]
    assert actual == (
        "6d28e558e7292bd018cdb27c849725b899eabf834540b9f0512a7c6b64d44faf"
    )


def test_baseline_sql_contains_no_application_row_data(baseline_sql):
    assert "\nCOPY " not in baseline_sql
    assert "\nINSERT INTO " not in baseline_sql


def test_baseline_sql_leaves_version_table_to_alembic(baseline_sql):
    assert "CREATE TABLE public.alembic_version" not in baseline_sql
    assert "ALTER TABLE ONLY public.alembic_version" not in baseline_sql
    assert "set_config('search_path', '', false)" not in baseline_sql


def test_source_object_counts_are_frozen(contract):
    source = contract["source_schema"]

    assert source["table_count_including_alembic"] == 27
    assert source["application_and_staging_table_count"] == 26
    assert source["sequence_count"] == 21
    assert source["explicit_index_count"] == 83
    assert source["add_constraint_count"] == 64
    assert source["inline_constraint_count"] == 2
    assert source["function_count"] == 1
    assert source["extension_count"] == 1


def test_baseline_sql_has_exact_application_table_inventory(contract, baseline_sql):
    expected = set(contract["expected_public_tables"]) - {"alembic_version"}

    assert _table_names(baseline_sql) == expected
    assert len(expected) == contract["baseline_sql"]["table_count"]


def test_reconstructed_inventory_includes_alembic_table(contract):
    expected = set(contract["expected_public_tables"])

    assert "alembic_version" in expected
    assert len(expected) == 27
    assert contract["baseline_sql"]["expected_table_count_after_alembic_upgrade"] == 27


def test_candidate_migration_is_one_root_revision():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign) is False
        and isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }

    # Values are annotated assignments, so the source assertions are deliberate.
    assert 'revision: str = "m12_source_state_001"' in source
    assert "down_revision: Union[str, Sequence[str], None] = None" in source
    assert assignments == {}


def test_candidate_migration_verifies_sql_checksum():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "BASELINE_SQL_SHA256" in source
    assert "sha256(sql.encode" in source
    assert "checksum mismatch" in source


def test_candidate_migration_does_not_use_create_all():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "create_all" not in source
    assert "exec_driver_sql(_verified_baseline_sql())" in source


def test_candidate_downgrade_is_explicitly_forward_only():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "def downgrade()" in source
    assert "forward-only" in source
    assert "discard the" in source


def test_historical_revision_hashes_are_frozen(contract):
    assert contract["historical_migrations"] == {
        "577f5fc9b121_lock_receipt_no_and_cleanup_sales.py": (
            "2bf2e6a1e8762dcbb432f9ea3ce8d5c22df06e8548aeffe697efbaf45f7c2d25"
        ),
        "5c706797029a_add_treasury_logs.py": (
            "a619d98ef5eee35ccb080147bdc699d038bd41ea8a671e2ddc698426b93ba29e"
        ),
        "86322f59e0de_baseline_existing_db.py": (
            "9ea31edec8624f21606a6ae56fbdcf50a7fa274293dbd83ae1c1200bcdba0852"
        ),
        "fff36dab3483_add_tier1_business_tables.py": (
            "fe5f26bf2a0cda2d4ea16ec1f9e626804614207237a2dbca060b031873eb0946"
        ),
    }


def test_reconstruction_config_points_only_to_candidate_directory():
    source = RECONSTRUCTION_CONFIG_PATH.read_text(encoding="utf-8")
    env_source = RECONSTRUCTION_ENV_PATH.read_text(encoding="utf-8")

    assert "script_location = %(here)s/alembic_reconstruction" in source
    assert "alembic/versions" not in source
    assert '"version_table_schema": "public"' in env_source


def test_main_alembic_configuration_remains_active():
    source = MAIN_CONFIG_PATH.read_text(encoding="utf-8")

    assert "script_location = %(here)s/alembic" in source


def test_authority_decision_preserves_main_lineage_and_stamps(contract):
    decision = contract["authority_decision"]

    assert decision["main_alembic_lineage_changed"] is False
    assert decision["existing_database_stamp_changed"] is False
    assert decision["historical_revision_modified"] is False
    assert decision["candidate_is_production_authority"] is False
    assert decision["activation_requires_separate_approval"] is True


def test_safety_boundary_names_one_disposable_database(contract):
    boundary = contract["safety_boundary"]

    assert boundary["allowed_database_name"] == RECONSTRUCTION_DATABASE_NAME
    assert boundary["production_use_allowed"] is False
    assert boundary["parity_database_use_allowed"] is False
    assert boundary["test_database_use_allowed"] is False


def test_policy_accepts_named_localhost_database():
    url = validate_reconstruction_url(
        f"postgresql+psycopg2://user:pass@localhost:5432/{RECONSTRUCTION_DATABASE_NAME}"
    )

    assert url.database == RECONSTRUCTION_DATABASE_NAME
    assert url.host == "localhost"


def test_policy_rejects_wrong_database():
    with pytest.raises(UnsafeReconstructionTarget, match="Refusing database"):
        validate_reconstruction_url(
            "postgresql+psycopg2://user:pass@localhost:5432/xbos"
        )


def test_policy_rejects_remote_host():
    with pytest.raises(UnsafeReconstructionTarget, match="non-local"):
        validate_reconstruction_url(
            "postgresql+psycopg2://user:pass@db.example.com:5432/"
            f"{RECONSTRUCTION_DATABASE_NAME}"
        )


def test_policy_rejects_non_postgresql_backend():
    with pytest.raises(UnsafeReconstructionTarget, match="requires PostgreSQL"):
        validate_reconstruction_url(
            f"sqlite:///{RECONSTRUCTION_DATABASE_NAME}"
        )


def test_runner_exposes_guarded_lifecycle_actions():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    for action in ("status", "create-and-verify", "verify-existing", "drop"):
        assert f'"{action}"' in source
    assert "Refusing to overwrite existing database" in source
    assert "was retained" in source


def test_runner_requires_exact_confirmation_before_drop():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    assert "--confirm-database-name" in source
    assert "confirmation != RECONSTRUCTION_DATABASE_NAME" in source
    assert "WITH (FORCE)" in source
    assert "SELECT version_num FROM public.alembic_version" in source


def test_exit_gate_requires_clean_room_proof_without_activation(contract):
    gate = set(contract["exit_gate"])

    assert "fresh_disposable_database_upgrades_to_candidate_head" in gate
    assert "reconstructed_public_table_inventory_matches_contract" in gate
    assert "main_alembic_lineage_remains_unchanged" in gate
    assert "existing_database_stamps_remain_unchanged" in gate
    assert "all_tests_pass" in gate
