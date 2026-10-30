"""SWES R2 WND fixture candidate static/fail-closed checks; no hosted DB or writes."""
from __future__ import annotations

import re
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts.swes_r2_wnd_synthetic_fixture_bootstrap import (
    BRANCH_CODE,
    CATALOG_CODE,
    EXPECTED_DB,
    EXPECTED_ROLE,
    IDS,
    INSERTS,
    PRICE_CODE,
    TABLES,
    TENANT,
    TENANT_CODE,
    _parameters,
    execute,
)

ROOT = Path(__file__).resolve().parents[2]


def test_literal_tenant_is_not_physical_wnd_and_host_is_exact():
    assert TENANT == 910001
    assert TENANT != 2
    assert EXPECTED_DB == "wnd_xafpay_demo_austin_db"
    assert EXPECTED_ROLE == "wnd_xafpay_demo_austin_db_user"


def test_idempotent_synthetic_namespace_is_unique():
    assert len(set(IDS.values())) == len(IDS)
    assert len(IDS) == 8
    assert all(str(item.version) == "5" for item in IDS.values())


def test_no_real_payment_or_checkout_issuance():
    assert len(INSERTS) == 11
    assert {name for name, _ in INSERTS} == {
        "tenant", "branch", "organization", "location",
        "legacy_branch_mapping", "pa_merchant", "atomic_unit",
        "catalog", "catalog_entry", "price", "catalog_binding",
    }
    assert not any(
        re.search(r"\b(UPDATE|DELETE|DROP|ALTER|GRANT|REVOKE|TRUNCATE)\b", sql.upper())
        for _, sql in INSERTS
    )
    assert all("credential" not in sql.lower() for _, sql in INSERTS)
    assert all("payment_" not in sql.lower() for _, sql in INSERTS)


def test_registered_not_forged_operational_merchant():
    merchant = dict(INSERTS)["pa_merchant"]
    assert "'registered'" in merchant
    assert "'operational'" not in merchant


def test_xaf_price_comes_only_from_server_owned_sql():
    params = _parameters()
    assert PRICE_CODE == "swes-retail"
    assert params["price_code"] == PRICE_CODE
    assert params["effective"].tzinfo is timezone.utc
    assert "'XAF'" in dict(INSERTS)["price"]
    assert "1000" in dict(INSERTS)["price"]
    assert CATALOG_CODE == "SWES-WND-AUSTIN"


def test_no_unknown_sql_bind_parameters():
    names = set(_parameters()) | {
        "branch_id", "organization_id", "location_id", "unit_id", "catalog_id",
    }
    for label, statement in INSERTS:
        assert not (set(text(statement)._bindparams) - names), label


def test_source_ddl_references_are_actual_not_invented():
    source = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "alembic_neutral/sql/m13_financial_foundation_up.sql",
            "alembic_neutral/sql/pc1_structural_context_up.sql",
            "alembic_neutral/sql/pa0123_merchant_lifecycle_subscriptions_onboarding_up.sql",
            "alembic_neutral/sql/so1_atomic_catalog_offer_pricing_up.sql",
            "alembic_neutral/sql/cc_catalog_binding_registry_up.sql",
        )
    )
    for table in (
        "organization_units", "locations", "legacy_branch_structural_mappings",
        "pa_merchants", "so1_catalogs", "so1_catalog_entries", "so1_prices",
        "restaurant_customer_catalog_read_bindings",
    ):
        assert re.search(rf"CREATE TABLE public\.{table}\s*\(", source)
    assert "registered" in source
    assert "ck_cc_catalog_binding_currency" in source


def test_require_owner_attestation_before_hosted_database_connection(monkeypatch):
    monkeypatch.delenv("SWES_WND_OWNER_ATTESTED_SYNTHETIC_ONLY", raising=False)
    import scripts.swes_r2_wnd_synthetic_fixture_bootstrap as target

    def forbidden_connection(*_args, **_kwargs):
        raise AssertionError("unexpected_db_connection")

    monkeypatch.setattr(target, "create_engine", forbidden_connection)
    with pytest.raises(RuntimeError, match="ATTESTATION_REQUIRED"):
        execute("postgresql+psycopg://fake@fake.invalid/fake", "apply", hosted=True)


def test_tenant_code_scoped_to_synthetic_campaign():
    assert TENANT_CODE == "SWES_WND_AUSTIN_TEST"
    assert BRANCH_CODE == "SWES-AUSTIN-TEST"
    assert len(TABLES) == 14
    assert TABLES["r1_restaurant_orders"] == "tenant_id"
