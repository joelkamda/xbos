import copy
import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT / "contracts" / "persistence" / "v1"
    / "m20_canonical_event_catalog_seed.json"
)
MIGRATION_PATH = (
    ROOT / "alembic_neutral" / "versions"
    / "m20_event_catalog_003_seed_canonical_event_catalog.py"
)

from core.persistence.m20_event_catalog import (
    CATALOG_CODE,
    CATALOG_VERSION,
    CONTRACT_REVISION,
    EXPECTED_CATALOG_SEMANTIC_SHA256,
    EXPECTED_EVENT_COUNT,
    RECONCILIATION_EFFECTS,
    CatalogSeedError,
    build_seed_rows,
    canonical_json_bytes,
    load_catalog,
    semantic_sha256,
    validate_catalog,
)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def rows():
    return build_seed_rows()


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_seed_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M20_CANONICAL_EVENT_CATALOG_SEED"
    assert contract["contract_version"] == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_source_authority_matches_m0(contract):
    source = contract["source_authority"]
    assert source["catalog_code"] == CATALOG_CODE
    assert source["catalog_version"] == CATALOG_VERSION
    assert source["contract_revision"] == CONTRACT_REVISION
    assert source["semantic_sha256"] == EXPECTED_CATALOG_SEMANTIC_SHA256


def test_approved_catalog_fingerprint_is_stable(catalog):
    assert semantic_sha256(catalog) == EXPECTED_CATALOG_SEMANTIC_SHA256
    assert canonical_json_bytes(catalog) == canonical_json_bytes(catalog)


def test_catalog_source_validation_passes(catalog):
    validate_catalog(catalog)


def test_catalog_content_drift_is_rejected(catalog):
    altered = copy.deepcopy(catalog)
    altered["event_types"][0]["definition"] += " altered"
    with pytest.raises(CatalogSeedError, match="fingerprint mismatch"):
        validate_catalog(altered)


def test_catalog_identity_drift_is_rejected(catalog):
    altered = copy.deepcopy(catalog)
    altered["contract_revision"] = 99
    with pytest.raises(CatalogSeedError, match="Unexpected catalog identity"):
        validate_catalog(altered)


def test_seed_contains_exactly_twenty_rows(rows):
    assert len(rows) == EXPECTED_EVENT_COUNT == 20


def test_seed_identities_are_unique(rows):
    identities = {
        (row["event_type_code"], row["event_version"]) for row in rows
    }
    assert len(identities) == len(rows)


def test_definition_hashes_are_unique_lowercase_sha256(rows):
    hashes = {row["definition_hash"] for row in rows}
    assert len(hashes) == len(rows)
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)


def test_definition_hashes_cover_complete_event_definitions(catalog, rows):
    source = {
        (event["event_type_code"], event["event_version"]): event
        for event in catalog["event_types"]
    }
    for row in rows:
        identity = (row["event_type_code"], row["event_version"])
        assert row["definition_hash"] == semantic_sha256(source[identity])
        assert row["metadata"]["event_definition"] == source[identity]


def test_catalog_fingerprint_is_retained_on_every_row(rows):
    assert {
        row["metadata"]["catalog_semantic_sha256"] for row in rows
    } == {EXPECTED_CATALOG_SEMANTIC_SHA256}


def test_account_role_policy_retains_executable_policy(catalog, rows):
    source = {
        (event["event_type_code"], event["event_version"]): event
        for event in catalog["event_types"]
    }
    for row in rows:
        event = source[(row["event_type_code"], row["event_version"])]
        policy = row["account_role_policy"]
        assert policy["allowed_economic_roles"] == event["allowed_economic_roles"]
        assert policy["requires_original_event"] == event["requires_original_event"]
        assert policy["source_record_kinds"] == event["source_record_kinds"]
        assert policy["required_classification_roles"] == event[
            "required_classification_roles"
        ]
        assert policy["operational_account_policy"] == event[
            "operational_account_policy"
        ]
        assert policy["reconciliation_policy"] == event["reconciliation_policy"]
        assert policy["posting_profiles"] == event["posting_profiles"]


def test_reconciliation_vocabulary_matches_approved_catalog(catalog, contract):
    assert set(RECONCILIATION_EFFECTS) == set(catalog["reconciliation_effects"])
    assert set(RECONCILIATION_EFFECTS) == set(
        contract["approved_reconciliation_effects"]
    )


def test_fixed_reconciliation_effects_are_stored_without_loss(catalog, rows):
    actual = {
        (row["event_type_code"], row["event_version"]): row[
            "reconciliation_effect"
        ]
        for row in rows
    }
    for event in catalog["event_types"]:
        if event["reconciliation_policy"]["mode"] == "fixed":
            identity = (event["event_type_code"], event["event_version"])
            assert actual[identity] == event["reconciliation_policy"]["effect"]


def test_payment_settled_uses_default_role_effect_and_retains_mapping(rows):
    row = next(row for row in rows if row["event_type_code"] == "PAYMENT_SETTLED")
    assert row["reconciliation_effect"] == "inflow"
    assert row["account_role_policy"]["reconciliation_policy"] == {
        "mode": "by_economic_role",
        "mappings": {"settlement_in": "inflow", "settlement_out": "outflow"},
    }


@pytest.mark.parametrize(
    "event_code",
    [
        "PAYMENT_SETTLEMENT_REVERSED",
        "PROVIDER_SETTLEMENT_ADJUSTED",
        "FINANCIAL_FACT_REVERSED",
    ],
)
def test_dynamic_reconciliation_events_defer_instance_effect(rows, event_code):
    row = next(row for row in rows if row["event_type_code"] == event_code)
    assert row["reconciliation_effect"] == "none"
    assert row["account_role_policy"]["reconciliation_policy"]["mode"] in {
        "inverse_original",
        "classification_dependent",
    }


def test_seed_rows_use_approved_effective_timestamp(catalog, rows):
    assert all(row["effective_to"] is None for row in rows)
    assert {
        row["approved_at"].isoformat().replace("+00:00", "Z") for row in rows
    } == {catalog["approved_at"]}
    assert {row["effective_from"] for row in rows} == {
        row["approved_at"] for row in rows
    }


def test_migration_has_canonical_linear_parent():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m20_event_catalog_003"' in source
    assert 'down_revision = "m13_financial_foundation_002"' in source


def test_migration_seeds_without_financial_event_or_outbox_writes():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "seed_catalog(op.get_bind())" in source
    assert "INSERT INTO public.financial_events" not in source
    assert "INSERT INTO public.outbox_messages" not in source


def test_migration_aligns_reconciliation_constraint_before_seed():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert source.index("_replace_effect_constraint(_APPROVED_EFFECTS)") < source.index(
        "seed_catalog(op.get_bind())"
    )


def test_downgrade_is_explicit_and_reenables_immutability_trigger():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "DISABLE TRIGGER tr_financial_event_types_immutable" in source
    assert "ENABLE TRIGGER tr_financial_event_types_immutable" in source
    assert "DELETE FROM public.financial_event_type_versions" in source


def test_contract_scope_excludes_event_engine_and_wnd_cutover(contract):
    excluded = set(contract["scope"]["excluded"])
    assert "financial event emission" in excluded
    assert "WND writer cutover" in excluded
    assert "historical transformation" in excluded
