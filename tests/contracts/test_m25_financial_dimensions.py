import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m25_financial_dimensions_and_posting_context.json"
UP_PATH = ROOT / "alembic_neutral" / "sql" / "m25_financial_dimensions_up.sql"
DOWN_PATH = ROOT / "alembic_neutral" / "sql" / "m25_financial_dimensions_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral" / "versions" / "m25_financial_dimensions_007_posting_context_dimensions.py"
CONTRACT_CODE_PATH = ROOT / "core" / "domain" / "finance" / "dimension_contract.py"
DIMENSION_REPOSITORY_PATH = ROOT / "core" / "domain" / "finance" / "dimension_repository.py"
POSTING_REPOSITORY_PATH = ROOT / "core" / "domain" / "finance" / "posting_repository.py"
POSTING_ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "posting_engine.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m25_financial_dimensions.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M25_FINANCIAL_DIMENSIONS"
    assert contract["contract_version"] == 1
    assert contract["package_revision"] == 2
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_committed_m24(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "c6e3b6d",
        "migration_revision": "m24_balanced_posting_006",
    }


def test_migration_is_linear_after_m24():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m25_financial_dimensions_007"' in source
    assert 'down_revision = "m24_balanced_posting_006"' in source
    assert "branch_labels = None" in source


@pytest.mark.parametrize(
    "table",
    [
        "financial_dimension_types",
        "financial_dimension_values",
        "posting_dimension_policies",
    ],
)
def test_dimension_tables_are_installed(table):
    assert f"CREATE TABLE public.{table}" in UP_PATH.read_text(encoding="utf-8")


def test_dimension_types_are_tenant_scoped_and_controlled():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, dimension_code)" in source
    assert "REFERENCES public.tenants(id)" in source
    assert "dimension_code ~ '^[a-z][a-z0-9_]{0,63}$'" in source


def test_dimension_values_are_tenant_and_type_scoped():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, dimension_type_id, value_code)" in source
    assert "REFERENCES public.financial_dimension_types(tenant_id, id)" in source
    assert "REFERENCES public.financial_dimension_values(tenant_id, dimension_type_id, id)" in source


def test_dimension_values_can_form_same_type_hierarchies():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "parent_value_id BIGINT NULL" in source
    assert "ck_financial_dimension_values_parent_not_self" in source


def test_policies_are_legal_entity_and_line_role_scoped():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "legal_entity_unit_id BIGINT NOT NULL" in source
    assert "posting_profile_code VARCHAR(80) NOT NULL" in source
    assert "account_role VARCHAR(80) NOT NULL" in source
    assert "REFERENCES public.organization_units(tenant_id, id)" in source


def test_policy_requirements_are_closed_enum():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "requirement IN ('required','optional','forbidden')" in source
    assert "requirement <> 'forbidden' OR default_dimension_value_id IS NULL" in source


def test_default_value_is_constrained_to_same_tenant_and_type():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "(tenant_id, dimension_type_id, default_dimension_value_id)" in source
    assert "REFERENCES public.financial_dimension_values(tenant_id, dimension_type_id, id)" in source


def test_configuration_is_effective_dated():
    source = UP_PATH.read_text(encoding="utf-8")
    assert source.count("effective_from DATE NOT NULL") == 3
    assert source.count("effective_to DATE NULL") == 3
    assert source.count("effective_to IS NULL OR effective_to >= effective_from") == 3


def test_configuration_history_cannot_be_deleted():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "xbos_reject_dimension_configuration_mutation" in source
    assert source.count("BEFORE UPDATE OR DELETE") == 3
    assert "deactivate or end-date it" in source
    assert "posting dimension policy semantics are immutable" in source
    assert "old_row ->> 'default_dimension_value_id' IS DISTINCT FROM" in source


def test_journal_snapshot_must_keep_dimensions_as_object():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "ck_journal_lines_financial_dimensions_object" in source
    assert "dimension_snapshot -> 'financial_dimensions'" in source


def test_sql_script_is_psycopg_percent_safe():
    assert "%" not in UP_PATH.read_text(encoding="utf-8")


def test_downgrade_removes_only_m25_objects():
    source = DOWN_PATH.read_text(encoding="utf-8")
    for table in (
        "posting_dimension_policies",
        "financial_dimension_values",
        "financial_dimension_types",
    ):
        assert f"DROP TABLE IF EXISTS public.{table}" in source
    assert "DROP TABLE IF EXISTS public.journal_lines" not in source
    assert "financial_events" not in source


def test_context_parses_global_and_role_values():
    from core.domain.finance.dimension_contract import parse_posting_dimension_context

    context = parse_posting_dimension_context(
        {
            "dimension_values": {"channel": "whatsapp"},
            "account_role_dimension_values": {
                "classified_revenue": {"cost_center": "sales"}
            },
        }
    )
    assert context.for_account_role("classified_revenue") == {
        "channel": "whatsapp",
        "cost_center": "sales",
    }
    assert context.for_account_role("trade_or_contract_receivable") == {
        "channel": "whatsapp"
    }


def test_role_value_overrides_global_value():
    from core.domain.finance.dimension_contract import parse_posting_dimension_context

    context = parse_posting_dimension_context(
        {
            "dimension_values": {"department": "default"},
            "account_role_dimension_values": {
                "classified_revenue": {"department": "sales"}
            },
        }
    )
    assert context.for_account_role("classified_revenue")["department"] == "sales"


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"dimension_values": []}, "invalid_dimension_context"),
        ({"dimension_values": {"Bad Code": "x"}}, "invalid_dimension_code"),
        ({"dimension_values": {"channel": ""}}, "invalid_dimension_value_code"),
        (
            {"account_role_dimension_values": {"Bad Role": {"channel": "x"}}},
            "invalid_dimension_account_role",
        ),
    ],
)
def test_context_rejects_invalid_shapes(payload, code):
    from core.domain.finance.dimension_contract import parse_posting_dimension_context
    from core.domain.finance.event_contract import FinancialEventValidationError

    with pytest.raises(FinancialEventValidationError) as exc:
        parse_posting_dimension_context(payload)
    assert exc.value.code == code


def test_context_rejects_override_for_unposted_role():
    from core.domain.finance.dimension_contract import parse_posting_dimension_context
    from core.domain.finance.event_contract import FinancialEventValidationError

    context = parse_posting_dimension_context(
        {"account_role_dimension_values": {"classified_expense": {"project": "p1"}}}
    )
    with pytest.raises(FinancialEventValidationError) as exc:
        context.assert_roles_allowed({"classified_revenue"})
    assert exc.value.code == "dimension_account_role_not_posted"


def test_policy_precedence_prefers_exact_profile_and_role():
    from core.domain.finance.dimension_repository import (
        DimensionPolicy,
        FinancialDimensionRepository,
    )

    generic = DimensionPolicy(1, "channel", "optional", None, None, None, False, False)
    profile = DimensionPolicy(1, "channel", "required", None, None, None, True, False)
    exact = DimensionPolicy(1, "channel", "required", None, None, None, True, True)
    selected = FinancialDimensionRepository._select_precedence((generic, profile, exact))
    assert selected["channel"] is exact


def test_equal_specificity_policy_is_rejected():
    from core.domain.finance.dimension_repository import (
        DimensionPolicy,
        FinancialDimensionRepository,
    )
    from core.domain.finance.event_contract import FinancialEventValidationError

    first = DimensionPolicy(1, "channel", "optional", None, None, None, True, True)
    second = DimensionPolicy(1, "channel", "required", None, None, None, True, True)
    with pytest.raises(FinancialEventValidationError) as exc:
        FinancialDimensionRepository._select_precedence((first, second))
    assert exc.value.code == "dimension_policy_ambiguous"


@pytest.mark.parametrize(
    "guard",
    [
        "dimension_not_allowed",
        "dimension_forbidden",
        "dimension_required",
        "dimension_default_mismatch",
        "dimension_policy_ambiguous",
        "dimension_value_missing",
        "dimension_value_ambiguous",
    ],
)
def test_repository_has_fail_closed_guard(guard):
    assert guard in DIMENSION_REPOSITORY_PATH.read_text(encoding="utf-8")


def test_repository_filters_type_policy_and_value_by_business_date():
    source = DIMENSION_REPOSITORY_PATH.read_text(encoding="utf-8")
    assert source.count("effective_from <= :business_date") >= 3
    assert source.count("effective_to IS NULL OR") >= 3
    assert "policy.active" in source
    assert "dimension.active" in source
    assert "AND active" in source


def test_repository_tenant_filters_every_resolution_query():
    source = DIMENSION_REPOSITORY_PATH.read_text(encoding="utf-8")
    assert source.count("tenant_id = :tenant_id") >= 2
    assert '"tenant_id": event.tenant_id' in source


def test_posting_engine_resolves_dimensions_per_account_role():
    source = POSTING_ENGINE_PATH.read_text(encoding="utf-8")
    assert "parse_posting_dimension_context" in source
    assert "resolve_line_snapshot" in source
    assert "account_role=account_role" in source
    assert '"financial_dimensions": financial_dimensions' in source


def test_inverse_original_corrections_inherit_original_dimensions():
    source = POSTING_ENGINE_PATH.read_text(encoding="utf-8")
    assert "correction_dimensions_immutable" in source
    assert "dimension_snapshot=dict(line.dimension_snapshot)" in source


def test_contract_distinguishes_inverse_and_template_corrections(contract):
    behavior = contract["posting_context"]
    assert behavior["correction_behavior"].startswith("inverse_original_profiles")
    assert behavior["dedicated_template_corrections"].startswith("resolve_their_own")


def test_verifier_uses_generic_reversal_only_for_expense_original():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'event_type_code="EXPENSE_RECOGNIZED"' in source
    assert 'event_type_code="FINANCIAL_FACT_REVERSED"' in source
    assert '"expense_source": source_ids["expense_transaction"]' in source
    assert '_correction_command(ids["reversal_source"], expense_event_id)' in source


def test_line_records_round_trip_dimension_snapshot():
    source = POSTING_REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "dimension_snapshot: Mapping[str, Any]" in source
    assert "dimension_snapshot=dict(row[\"dimension_snapshot\"])" in source
    assert "dict(line.dimension_snapshot), sort_keys=True" in source


def test_posting_still_uses_nested_transaction_and_never_commits():
    source = POSTING_ENGINE_PATH.read_text(encoding="utf-8")
    assert "with session.begin_nested():" in source
    assert ".commit(" not in source


def test_contract_keeps_kernel_industry_neutral(contract):
    assert contract["authority_boundaries"]["industry_pack"].startswith("may_seed")
    assert "restaurant" not in CONTRACT_PATH.read_text(encoding="utf-8").lower()
    assert "hotel" not in CONTRACT_PATH.read_text(encoding="utf-8").lower()
    assert "retail_store" not in CONTRACT_PATH.read_text(encoding="utf-8").lower()


def test_verifier_uses_exact_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m25_dimensions_test"' in source
    assert "Refusing unexpected test database" in source
    assert "--confirm-database-name" in source


def test_verifier_preserves_configured_database_credentials():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "application_engine.url.render_as_string(hide_password=False)" in source
    assert "make_url(str(application_engine.url))" not in source


@pytest.mark.parametrize(
    "proof",
    [
        "global_override=PASS",
        "required_default=PASS",
        "missing_forbidden=PASS",
        "tenant_isolation=PASS",
        "correction_inheritance=PASS",
        "immutability=PASS",
        "atomic_counts=PASS",
        "upgrade_downgrade_upgrade=PASS",
    ],
)
def test_verifier_reports_required_proof(proof):
    assert proof in VERIFIER_PATH.read_text(encoding="utf-8")


def test_wnd_cutover_and_dispatch_remain_deferred(contract):
    assert contract["compatibility"]["wnd_writer_cutover"] is False
    assert contract["compatibility"]["outbox_dispatch"] is False
    assert "wnd_writer_cutover" in contract["deferred"]
    assert "outbox_dispatch" in contract["deferred"]
