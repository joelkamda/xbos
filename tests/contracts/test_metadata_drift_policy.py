import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.persistence import alembic_policy


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = (
    ROOT / "contracts" / "persistence" / "v1" / "metadata_drift_baseline.json"
)
ALEMBIC_ENV_PATH = ROOT / "alembic" / "env.py"


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _table(name):
    return SimpleNamespace(name=name)


def _child(table_name):
    return SimpleNamespace(table=_table(table_name))


def _classified_tables(baseline):
    return {
        name
        for group in baseline["table_classifications"].values()
        for name in group
    }


def test_baseline_has_approved_identity(baseline):
    assert baseline["baseline_code"] == "XBOS_M1_METADATA_DRIFT_BASELINE"
    assert baseline["baseline_version"] == 1
    assert baseline["status"] == "approved"


def test_baseline_is_anchored_to_m1_0_and_current_revision(baseline):
    assert baseline["source_commit"] == "a967b93"
    assert baseline["database_revision"] == "5c706797029a"


def test_observed_table_counts_are_internally_consistent(baseline):
    assert baseline["database_table_count"] == 27
    assert baseline["orm_table_count"] == 21
    assert baseline["common_table_count"] == 21
    assert baseline["orm_only_tables"] == []


def test_all_observed_database_tables_are_classified_once(baseline):
    groups = list(baseline["table_classifications"].values())
    flattened = [name for group in groups for name in group]

    assert len(flattened) == baseline["database_table_count"]
    assert len(flattened) == len(set(flattened))


def test_classification_sizes_match_observation(baseline):
    groups = baseline["table_classifications"]

    assert len(groups["legacy_orm_tables"]) == 21
    assert len(groups["legacy_database_only_tables"]) == 2
    assert len(groups["staging_tables"]) == 3
    assert len(groups["alembic_internal_tables"]) == 1


def test_database_only_tables_are_recorded_explicitly(baseline):
    assert set(baseline["table_classifications"]["legacy_database_only_tables"]) == {
        "billable_unit_taxonomy",
        "idempotency_keys",
    }


def test_staging_tables_are_recorded_explicitly(baseline):
    assert set(baseline["table_classifications"]["staging_tables"]) == {
        "wnd_inventory_aliases",
        "wnd_inventory_real_staging",
        "wnd_inventory_staging",
    }


def test_comparison_notice_categories_sum_to_observed_total(baseline):
    assert sum(baseline["comparison_notice_categories"].values()) == 179
    assert baseline["comparison_notice_count"] == 179


def test_dangerous_drop_and_rewrite_notices_are_frozen(baseline):
    categories = baseline["comparison_notice_categories"]

    assert categories["removed_table"] == 5
    assert categories["removed_column"] == 9
    assert categories["removed_index"] == 29
    assert categories["removed_unique_constraint"] == 8
    assert categories["removed_foreign_key"] == 4


def test_baseline_records_financial_payload_type_risk(baseline):
    assert (
        "autogenerate_would_change_jsonb_to_json_on_financially_relevant_payloads"
        in baseline["risk_findings"]
    )


def test_policy_requires_handwritten_additive_migrations(baseline):
    policy = baseline["policy"]

    assert policy["canonical_migration_style"] == "handwritten_additive"
    assert policy["handwritten_migration_required_for_protected_tables"] is True
    assert policy["destructive_generated_operations_allowed"] is False


def test_policy_does_not_mark_database_only_or_staging_tables_for_drop(baseline):
    policy = baseline["policy"]

    assert policy["database_only_tables_are_drop_candidates"] is False
    assert policy["staging_tables_are_drop_candidates"] is False


def test_policy_constants_match_the_approved_baseline(baseline):
    groups = baseline["table_classifications"]

    assert alembic_policy.LEGACY_ORM_TABLES == frozenset(
        groups["legacy_orm_tables"]
    )
    assert alembic_policy.LEGACY_DATABASE_ONLY_TABLES == frozenset(
        groups["legacy_database_only_tables"]
    )
    assert alembic_policy.STAGING_TABLES == frozenset(groups["staging_tables"])
    assert alembic_policy.ALEMBIC_INTERNAL_TABLES == frozenset(
        groups["alembic_internal_tables"]
    )


def test_protected_table_union_is_complete(baseline):
    assert alembic_policy.PROTECTED_EXISTING_TABLES == _classified_tables(baseline)
    assert len(alembic_policy.PROTECTED_EXISTING_TABLES) == 27
    assert baseline["protected_table_count"] == 27


def test_include_object_excludes_every_protected_table():
    for table_name in alembic_policy.PROTECTED_EXISTING_TABLES:
        assert (
            alembic_policy.include_object(
                _table(table_name), table_name, "table", True, None
            )
            is False
        )


def test_include_object_excludes_children_of_protected_tables():
    for object_type in ("column", "index", "unique_constraint", "foreign_key_constraint"):
        assert (
            alembic_policy.include_object(
                _child("payment_intents"),
                "sample_object",
                object_type,
                False,
                None,
            )
            is False
        )


def test_include_object_keeps_new_canonical_tables_visible():
    for table_name in (
        "financial_accounts",
        "financial_postings",
        "payment_allocations",
        "outbox_messages",
    ):
        assert (
            alembic_policy.include_object(
                _table(table_name), table_name, "table", False, None
            )
            is True
        )


def test_include_object_keeps_children_of_new_canonical_tables_visible():
    assert (
        alembic_policy.include_object(
            _child("financial_postings"), "event_id", "column", False, None
        )
        is True
    )


def test_alembic_environment_installs_the_selection_policy():
    source = ALEMBIC_ENV_PATH.read_text(encoding="utf-8")

    assert "from core.persistence.alembic_policy import include_object" in source
    assert '"include_object": include_object' in source


def test_exit_gate_requires_clean_check_without_database_mutation(baseline):
    assert baseline["expected_post_policy_alembic_check"] == (
        "no_new_upgrade_operations_detected"
    )
    assert "alembic_check_is_clean_at_revision_5c706797029a" in baseline["exit_gate"]
    assert "no_database_object_is_mutated" in baseline["exit_gate"]
    assert "all_tests_pass" in baseline["exit_gate"]
