from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from restaurant.customer_channel.catalog_read import CatalogReadTransport
from restaurant.customer_channel.contracts import (
    CATALOG_CONTEXT_PURPOSE,
    CATALOG_READ_PRINCIPAL,
    CATALOG_READ_SCOPE,
    CATALOG_TOKEN_DIGEST_CURRENT_ENV,
    CATALOG_TOKEN_DIGEST_NEXT_ENV,
    CatalogReadBinding,
    CatalogReadError,
)
from restaurant.customer_channel.repository import SQLCatalogReadBindingRepository

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
TOKEN = "synthetic-r2-r3a-token"
MERCHANT = UUID("00000000-0000-0000-0000-000000000501")
LOCATION = UUID("00000000-0000-0000-0000-000000000502")
CATALOG = UUID("00000000-0000-0000-0000-000000000503")
CONTEXT = UUID("00000000-0000-0000-0000-000000000504")
BINDING = UUID("00000000-0000-0000-0000-000000000505")
@pytest.fixture(autouse=True)
def registry_auth(monkeypatch):
    monkeypatch.setenv(
        CATALOG_TOKEN_DIGEST_CURRENT_ENV,
        hashlib.sha256(TOKEN.encode("utf-8")).hexdigest(),
    )
    monkeypatch.delenv(CATALOG_TOKEN_DIGEST_NEXT_ENV, raising=False)


def context(*, tenant_id=2):
    return SimpleNamespace(
        tenant_id=tenant_id,
        public_id=CONTEXT,
        purpose_code=CATALOG_CONTEXT_PURPOSE,
        effective_from=NOW - timedelta(hours=1),
        effective_to=None,
        expires_at=NOW + timedelta(hours=1),
        ended_at=None,
    )


def binding(**overrides):
    values = dict(
        binding_ref=BINDING,
        binding_version=1,
        merchant_public_id=MERCHANT,
        location_public_id=LOCATION,
        tenant_id=2,
        catalog_public_id=CATALOG,
        price_code="retail",
        currency="XAF",
        scope_type="location",
        scope_id=1,
        effective_from=NOW - timedelta(minutes=10),
        effective_to=None,
        enabled=True,
    )
    values.update(overrides)
    return CatalogReadBinding(**values)


class FakeInteraction:
    def __init__(self, value=None):
        self.value = value or context()

    def context_binding_by_public_id(self, public_id):
        assert public_id == CONTEXT
        return self.value


class FakeR2:
    def __init__(self):
        self.calls = []

    def menu(self, *args):
        self.calls.append(args)
        return {
            "tenant_id": args[0],
            "catalog_public_id": str(args[1]),
            "effective_at": args[2].isoformat(),
            "price_code": args[3],
            "currency": args[4],
            "scope_type": args[5],
            "scope_id": args[6],
        }


class FakeBindingRepository:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = []

    def resolve(self, merchant_public_id, location_public_id, effective_at):
        self.calls.append((merchant_public_id, location_public_id, effective_at))
        return self.rows
def service(rows, *, context_value=None):
    r2 = FakeR2()
    repo = FakeBindingRepository(rows)
    adapters = SimpleNamespace(
        interaction=FakeInteraction(context_value),
        r2=r2,
    )
    return (
        CatalogReadTransport(
            adapters=adapters,
            binding_repository=repo,
        ),
        repo,
        r2,
    )


def auth_kwargs():
    return dict(
        raw_token=TOKEN,
        principal=CATALOG_READ_PRINCIPAL,
        scopes=CATALOG_READ_SCOPE,
        correlation_ref="corr-r3a",
    )


def menu_call(value, **overrides):
    args = dict(
        context_binding_ref=CONTEXT,
        merchant_public_id=MERCHANT,
        location_public_id=LOCATION,
        binding_ref=BINDING,
        binding_version=1,
        effective_at=NOW,
        **auth_kwargs(),
    )
    args.update(overrides)
    return value.menu(**args)


def error_code(fn):
    with pytest.raises(CatalogReadError) as exc:
        fn()
    return exc.value.code
def test_zero_binding_fail_closed():
    value, _, r2 = service(())
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_MISSING"
    assert r2.calls == []


def test_one_active_effective_binding_resolves():
    value, repo, r2 = service((binding(),))
    result = menu_call(value)
    assert repo.calls == [(MERCHANT, LOCATION, NOW)]
    assert len(r2.calls) == 1
    assert r2.calls[0] == (
        2,
        CATALOG,
        NOW,
        "retail",
        "XAF",
        "location",
        1,
    )
    assert result["catalog_public_id"] == str(CATALOG)


def test_multiple_active_binding_fails():
    value, _, r2 = service(
        (
            binding(),
            binding(binding_ref=UUID("00000000-0000-0000-0000-000000000599")),
        )
    )
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_AMBIGUOUS"
    assert r2.calls == []


def test_inactive_binding_fails():
    value, _, r2 = service((binding(enabled=False),))
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_STALE"
    assert r2.calls == []
def test_expired_binding_fails():
    value, _, r2 = service(
        (binding(effective_to=NOW - timedelta(seconds=1)),)
    )
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_STALE"
    assert r2.calls == []


def test_future_binding_fails():
    value, _, r2 = service(
        (binding(effective_from=NOW + timedelta(seconds=1)),)
    )
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_STALE"
    assert r2.calls == []


def test_version_replay_stable():
    value, _, r2 = service((binding(binding_version=7),))
    first = menu_call(value, binding_version=7)
    second = menu_call(value, binding_version=7)
    assert first == second
    assert len(r2.calls) == 2
    assert error_code(
        lambda: menu_call(value, binding_version=8)
    ) == "CATALOG_BINDING_VERSION_MISMATCH"


def test_tenant_mismatch_fails():
    value, _, r2 = service((binding(tenant_id=3),))
    assert error_code(lambda: menu_call(value)) == "CATALOG_BINDING_MISMATCH"
    assert r2.calls == []
class FakeMappingsResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return FakeMappingsResult(self.rows)


def test_sql_repository_lookup_and_resolved_contract():
    row = {
        "binding_ref": BINDING,
        "binding_version": 4,
        "merchant_public_id": MERCHANT,
        "location_public_id": LOCATION,
        "tenant_id": 2,
        "catalog_public_id": CATALOG,
        "price_code": "retail",
        "currency": "XAF",
        "scope_type": "location",
        "scope_id": 1,
        "effective_from": NOW - timedelta(minutes=1),
        "effective_to": None,
        "active": True,
    }
    session = FakeSession([row])
    repo = SQLCatalogReadBindingRepository(session)
    result = repo.resolve(MERCHANT, LOCATION, NOW)
    assert len(result) == 1
    resolved = result[0]
    assert resolved.binding_ref == BINDING
    assert resolved.binding_version == 4
    assert resolved.tenant_id == 2
    assert resolved.catalog_public_id == CATALOG
    assert resolved.price_code == "retail"
    assert resolved.currency == "XAF"
    assert resolved.scope_type == "location"
    assert resolved.scope_id == 1
    assert session.params == {
        "merchant": str(MERCHANT),
        "location": str(LOCATION),
        "at": NOW,
    }
    assert "b.active=true" in session.statement
    assert "b.effective_from<=:at" in session.statement
    assert ":at<b.effective_to" in session.statement


def test_migration_revision_and_registry_schema_source():
    migration = (
        ROOT / "alembic_neutral" / "versions" / "cc_catalog_binding_registry_048.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "cc_catalog_binding_registry_048"' in migration
    assert (
        'down_revision = "cch_customer_channel_checkout_authority_047"'
        in migration
    )
    sql = (
        ROOT / "alembic_neutral" / "sql" / "cc_catalog_binding_registry_up.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE public.restaurant_customer_catalog_read_bindings" in sql
    table_block = sql.split(
        "CREATE TABLE public.restaurant_customer_catalog_read_bindings",
        1,
    )[1].split(");", 1)[0]
    required = (
        "public_id UUID",
        "tenant_id INTEGER",
        "merchant_public_id UUID",
        "location_id BIGINT",
        "catalog_public_id UUID",
        "active BOOLEAN",
        "effective_from TIMESTAMPTZ",
        "effective_to TIMESTAMPTZ",
        "row_version INTEGER",
        "price_code VARCHAR",
        "currency CHAR",
        "scope_type VARCHAR",
        "scope_id BIGINT",
    )
    for fragment in required:
        assert fragment in table_block
    lowered = table_block.lower()
    assert "catalog_item" not in lowered
    assert "product_name" not in lowered
    assert "currency_amount" not in lowered
    assert "price_amount" not in lowered
    assert "menu_section" not in lowered


def test_migration_enforces_active_window_uniqueness_and_tenant_integrity():
    sql = (
        ROOT / "alembic_neutral" / "sql" / "cc_catalog_binding_registry_up.sql"
    ).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in sql
    assert "overlapping_active_catalog_read_binding" in sql
    assert "tstzrange(" in sql
    assert "cross_tenant_catalog_binding_merchant" in sql
    assert "cross_tenant_catalog_binding_catalog" in sql
    assert "NEW.row_version := OLD.row_version + 1" in sql
