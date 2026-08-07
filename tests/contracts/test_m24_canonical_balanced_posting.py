import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m24_canonical_balanced_posting.json"
EVENT_CATALOG_PATH = ROOT / "contracts" / "finance" / "v1" / "financial_event_catalog.json"
ROLE_CATALOG_PATH = ROOT / "contracts" / "finance" / "v1" / "account_role_catalog.json"
UP_PATH = ROOT / "alembic_neutral" / "sql" / "m24_balanced_posting_up.sql"
DOWN_PATH = ROOT / "alembic_neutral" / "sql" / "m24_balanced_posting_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral" / "versions" / "m24_balanced_posting_006_canonical_balanced_journals.py"
CONTRACT_CODE_PATH = ROOT / "core" / "domain" / "finance" / "posting_contract.py"
REPOSITORY_PATH = ROOT / "core" / "domain" / "finance" / "posting_repository.py"
ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "posting_engine.py"
ATOMIC_PATH = ROOT / "core" / "domain" / "finance" / "atomic_posting_engine.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m24_canonical_balanced_posting.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M24_CANONICAL_BALANCED_POSTING"
    assert contract["contract_version"] == 1
    assert contract["status"] == "approved_implementation_candidate"
    assert contract["package_revision"] == 2


def test_contract_is_anchored_to_committed_m23(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "59f3747",
        "migration_revision": "m23_reversal_capacity_005",
    }


def test_migration_is_one_linear_revision():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m24_balanced_posting_006"' in source
    assert 'down_revision = "m23_reversal_capacity_005"' in source
    assert "branch_labels = None" in source


@pytest.mark.parametrize(
    "table",
    [
        "ledger_accounts",
        "accounting_periods",
        "ledger_account_role_bindings",
        "journal_entries",
        "journal_lines",
        "journal_entry_event_links",
    ],
)
def test_required_formal_accounting_tables_are_installed(table):
    assert f"CREATE TABLE public.{table}" in UP_PATH.read_text(encoding="utf-8")


def test_ledger_accounts_are_tenant_and_legal_entity_scoped():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, legal_entity_unit_id, account_code)" in source
    assert "REFERENCES public.organization_units(tenant_id, id)" in source


def test_role_bindings_are_currency_and_effective_date_aware():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "account_role VARCHAR(80) NOT NULL" in source
    assert "binding_key VARCHAR(160) NOT NULL DEFAULT 'default'" in source
    assert "currency_code VARCHAR(12) NOT NULL" in source
    assert "effective_from DATE NOT NULL" in source
    assert "effective_to DATE NULL" in source


def test_journal_line_rejects_two_sided_or_zero_sided_amounts():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "ck_journal_lines_transaction_side" in source
    assert "transaction_debit_amount > 0 AND transaction_credit_amount = 0" in source
    assert "transaction_debit_amount = 0 AND transaction_credit_amount > 0" in source


def test_posted_balance_is_deferred_until_transaction_end():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "CREATE CONSTRAINT TRIGGER trg_journal_entries_balanced" in source
    assert "CREATE CONSTRAINT TRIGGER trg_journal_lines_balanced" in source
    assert source.count("DEFERRABLE INITIALLY DEFERRED") >= 2
    assert "line_count < 2" in source
    assert "transaction_debits <> transaction_credits" in source
    assert "base_debits <> base_credits" in source


def test_posted_entries_and_lines_are_database_immutable():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "trg_journal_entries_immutable" in source
    assert "trg_journal_lines_immutable" in source
    assert "BEFORE UPDATE OR DELETE ON public.journal_entries" in source
    assert "BEFORE UPDATE OR DELETE ON public.journal_lines" in source
    assert "post a correcting entry" in source


def test_sql_script_is_psycopg_percent_safe():
    assert "%" not in UP_PATH.read_text(encoding="utf-8")


def test_downgrade_removes_only_m24_objects():
    source = DOWN_PATH.read_text(encoding="utf-8")
    for table in (
        "journal_entry_event_links",
        "journal_lines",
        "journal_entries",
        "ledger_account_role_bindings",
        "accounting_periods",
        "ledger_accounts",
    ):
        assert f"DROP TABLE IF EXISTS public.{table}" in source
    assert "financial_events" not in source
    assert "outbox_messages" not in source


def test_executable_profiles_exactly_cover_approved_catalog():
    from core.domain.finance.posting_contract import EVENT_PROFILES, NON_POSTING_EVENTS

    catalog = json.loads(EVENT_CATALOG_PATH.read_text(encoding="utf-8"))
    expected = {
        item["event_type_code"]: tuple(
            profile["profile_code"] for profile in item["posting_profiles"]
        )
        for item in catalog["event_types"]
        if item["posting_profiles"]
    }
    assert EVENT_PROFILES == expected
    expected_nonposting = {
        item["event_type_code"]
        for item in catalog["event_types"]
        if not item["posting_eligible"]
    }
    assert NON_POSTING_EVENTS == expected_nonposting


def test_executable_role_policy_exactly_covers_approved_catalog():
    from core.domain.finance.posting_contract import ACCOUNT_ROLE_POLICIES

    catalog = json.loads(ROLE_CATALOG_PATH.read_text(encoding="utf-8"))
    assert set(ACCOUNT_ROLE_POLICIES) == {
        item["account_role"] for item in catalog["account_roles"]
    }
    for item in catalog["account_roles"]:
        account_types, normal_balances, operational = ACCOUNT_ROLE_POLICIES[
            item["account_role"]
        ]
        assert account_types == frozenset(item["allowed_account_types"])
        assert normal_balances == frozenset(item["allowed_normal_balances"])
        assert operational == item["operational_account_link"]


def test_single_profile_is_selected_automatically():
    from core.domain.finance.posting_contract import select_posting_profile

    selected = select_posting_profile("COMMERCIAL_REVENUE_RECOGNIZED", {})
    assert selected.profile_code == "commercial_recognition"


def test_multiple_profiles_require_explicit_selection():
    from core.domain.finance.event_contract import FinancialEventValidationError
    from core.domain.finance.posting_contract import select_posting_profile

    with pytest.raises(FinancialEventValidationError) as exc:
        select_posting_profile("PAYMENT_SETTLED", {})
    assert exc.value.code == "posting_profile_required"


def test_profile_cannot_cross_event_types():
    from core.domain.finance.event_contract import FinancialEventValidationError
    from core.domain.finance.posting_contract import select_posting_profile

    with pytest.raises(FinancialEventValidationError) as exc:
        select_posting_profile(
            "PAYMENT_SETTLED", {"posting_profile_code": "expense_accrual"}
        )
    assert exc.value.code == "posting_profile_not_allowed"


def test_obligation_opened_is_explicitly_nonposting():
    from core.domain.finance.posting_contract import select_posting_profile

    assert select_posting_profile("OBLIGATION_OPENED", {}) is None


def test_binding_keys_are_role_specific_and_defaulted():
    from core.domain.finance.posting_contract import binding_key_for

    context = {"account_role_binding_keys": {"classified_revenue": "food-sales"}}
    assert binding_key_for(context, "classified_revenue") == "food-sales"
    assert binding_key_for(context, "trade_or_contract_receivable") == "default"


def test_repository_locks_event_before_posting_resolution():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "FROM public.financial_events" in source
    assert "FOR UPDATE" in source


def test_replay_join_uses_an_explicit_qualified_projection():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "_ENTRY_SELECT_COLUMNS" in source
    assert "SELECT {_ENTRY_SELECT_COLUMNS}" in source
    assert "je.tenant_id AS tenant_id" in source
    assert "je.id AS id" in source
    assert "SELECT je.*" not in source


def test_repository_collects_binding_results_before_cardinality_checks():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    binding = source[source.index("def resolve_account_binding"):source.index("def load_original_posting_lines")]
    assert "rows = session.execute(" in binding
    assert ").mappings().all()" in binding
    assert "if not rows:" in binding
    assert "if len(rows) != 1:" in binding
    assert "row = rows[0]" in binding


def test_repository_maps_only_declared_record_fields():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "JournalEntryRecord(**dict(row))" not in source
    assert "JournalLineRecord(**dict(line))" not in source
    assert "id=int(row[\"id\"])" in source
    assert "lines=tuple(cls._line_from_row(line) for line in lines)" in source


def test_primary_posting_replay_fails_closed_on_duplicates():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    replay = source[source.index("def find_for_event"):source.index("def _entry_from_row")]
    assert "LIMIT 2" in replay
    assert ").mappings().all()" in replay
    assert "primary_posting_ambiguous" in replay


def test_original_posting_lookup_fails_closed_on_duplicates():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    original = source[source.index("def load_original_posting_lines"):source.index("def insert_posted_entry")]
    assert "LIMIT 2" in original
    assert "original_posting_ambiguous" in original


def test_repository_resolves_exactly_one_open_period():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "period_state IN ('open','reopened')" in source
    assert "accounting_period_not_open" in source
    assert "accounting_period_ambiguous" in source


@pytest.mark.parametrize(
    "guard",
    [
        "account_role_unbound",
        "account_role_binding_ambiguous",
        "account_role_type_mismatch",
        "account_role_balance_mismatch",
        "account_currency_mismatch",
        "operational_link_forbidden",
        "operational_link_required",
        "operational_link_mismatch",
    ],
)
def test_repository_has_fail_closed_binding_guard(guard):
    assert guard in REPOSITORY_PATH.read_text(encoding="utf-8")


def test_repository_writes_draft_lines_link_then_posts():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    draft = source.index("'draft'")
    lines = source.index("INSERT INTO public.journal_lines")
    link = source.index("INSERT INTO public.journal_entry_event_links")
    posted = source.index("SET entry_state = 'posted'")
    assert draft < lines < link < posted


def test_posting_engine_never_commits():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "session.begin_nested()" in source
    assert ".commit(" not in source


def test_posting_engine_replays_existing_journal():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "find_for_event" in source
    assert "if existing is not None" in source


def test_posting_engine_rejects_fx_in_m24():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "fx_posting_deferred" in source


def test_inverse_posting_uses_original_accounts_and_opposite_side():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "load_original_posting_lines" in source
    assert '"credit" if original_side == "debit" else "debit"' in source


def test_atomic_orchestrator_wraps_event_and_posting_together():
    source = ATOMIC_PATH.read_text(encoding="utf-8")
    assert "with session.begin_nested():" in source
    assert "event_engine.emit" in source
    assert "posting_engine.post" in source
    assert source.index("event_engine.emit") < source.index("posting_engine.post")
    assert ".commit(" not in source


def test_verifier_uses_exact_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m24_posting_test"' in source
    assert "Refusing unexpected test database" in source
    assert "--confirm-database-name" in source


@pytest.mark.parametrize(
    "proof",
    [
        "template=PASS",
        "replay=PASS",
        "inverse_original=PASS",
        "period_guard=PASS",
        "role_binding=PASS",
        "balance_trigger=PASS",
        "immutability=PASS",
        "atomic_counts=3/3/3/3/6/3",
        "upgrade_downgrade_upgrade=PASS",
    ],
)
def test_verifier_reports_required_proof(proof):
    assert proof in VERIFIER_PATH.read_text(encoding="utf-8")


def test_wnd_cutover_and_outbox_dispatch_remain_deferred(contract):
    assert contract["compatibility"]["wnd_writer_cutover"] is False
    assert contract["compatibility"]["outbox_dispatch"] is False
    assert "wnd_writer_cutover" in contract["deferred"]
    assert "outbox_dispatch" in contract["deferred"]
