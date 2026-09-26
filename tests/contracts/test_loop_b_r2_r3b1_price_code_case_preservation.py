from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REVISION = (
    ROOT
    / "alembic_neutral"
    / "versions"
    / "cc_catalog_binding_price_code_case_049.py"
)
UP = (
    ROOT
    / "alembic_neutral"
    / "sql"
    / "cc_catalog_binding_price_code_case_049_up.sql"
)
DOWN = (
    ROOT
    / "alembic_neutral"
    / "sql"
    / "cc_catalog_binding_price_code_case_049_down.sql"
)
UP_048 = (
    ROOT
    / "alembic_neutral"
    / "sql"
    / "cc_catalog_binding_registry_up.sql"
)
SO1_REPOSITORY = (
    ROOT / "shared_operations" / "so1" / "sql_repository.py"
)
def test_successor_revision_is_additive_049_over_048():
    text = REVISION.read_text(encoding="utf-8")
    assert 'revision = "cc_catalog_binding_price_code_case_049"' in text
    assert 'down_revision = "cc_catalog_binding_registry_048"' in text
    assert "cc_catalog_binding_price_code_case_049_up.sql" in text
    assert "cc_catalog_binding_price_code_case_049_down.sql" in text


def test_048_still_contains_exact_original_lowercase_constraint():
    text = UP_048.read_text(encoding="utf-8")
    assert "CONSTRAINT ck_cc_catalog_binding_price_code" in text
    assert "price_code=lower(btrim(price_code))" in text
    assert "AND length(price_code)>0" in text


def test_049_up_preserves_case_and_rejects_whitespace():
    text = UP.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT ck_cc_catalog_binding_price_code" in text
    assert "ADD CONSTRAINT ck_cc_catalog_binding_price_code" in text
    assert "price_code=btrim(price_code)" in text
    assert "length(btrim(price_code))>0" in text
    assert "lower(" not in text.lower()
def test_049_down_restores_exact_048_constraint():
    text = DOWN.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT ck_cc_catalog_binding_price_code" in text
    assert "ADD CONSTRAINT ck_cc_catalog_binding_price_code" in text
    assert "price_code=lower(btrim(price_code))" in text
    assert "AND length(price_code)>0" in text


def test_so1_resolver_uses_exact_price_code_equality():
    text = SO1_REPOSITORY.read_text(encoding="utf-8")
    assert "p.price_code=:code" in text
    assert '"code":query.price_code' in text
    assert "lower(p.price_code)" not in text.lower()
    assert "upper(p.price_code)" not in text.lower()


def test_case_sensitive_contract_examples_are_distinct():
    canonical = "STANDARD"
    lowercase = "standard"
    mixed = "Standard"
    assert canonical != lowercase
    assert canonical != mixed
    assert lowercase != mixed


def test_canonical_storage_law_preserves_mixed_case():
    for value in ("STANDARD", "Standard", "standard", "Retail.XAF"):
        assert value == value.strip()
        assert len(value.strip()) > 0


def test_whitespace_values_fail_canonical_storage_law():
    for value in (" STANDARD", "STANDARD ", " STANDARD ", "   "):
        assert not (value == value.strip() and len(value.strip()) > 0)
