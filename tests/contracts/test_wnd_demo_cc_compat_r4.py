from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://r4:r4@127.0.0.1:1/r4_contract_only",
)

from database import get_db
from restaurant.customer_channel import router as router_module
from restaurant.customer_channel.catalog_read import CatalogReadTransport
from restaurant.customer_channel.contracts import (
    CATALOG_CONTEXT_PURPOSE,
    CATALOG_READ_PRINCIPAL,
    CATALOG_READ_SCOPE,
    CATALOG_TOKEN_DIGEST_CURRENT_ENV,
    CatalogReadBinding,
    CatalogReadError,
    RICH_CONTEXT_SCHEMA,
)
from restaurant.r1.contracts import ResourceRole, ServiceMode

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
TOKEN = "r4-synthetic-catalog-reader"
CONTEXT_ID = UUID("1f412ad2-0d08-4bb5-9524-421f422e469b")
MERCHANT_ID = UUID("8f75338c-aa7f-4eda-ba35-43f63dae9c1b")
LOCATION_ID = UUID("0b5b72b7-e637-4dc7-af76-9bb4150cf935")
CATALOG_ID = UUID("a92212f5-e464-4046-a469-b24683e96d68")
BINDING_ID = UUID("2fcc115e-66a0-4bd0-8f7e-4c837b0c5a4c")
TABLE_ID = UUID("00000000-0000-0000-0000-00000000a001")
AREA_ID = UUID("00000000-0000-0000-0000-00000000a002")


@pytest.fixture(autouse=True)
def auth(monkeypatch):
    monkeypatch.setenv(
        CATALOG_TOKEN_DIGEST_CURRENT_ENV,
        hashlib.sha256(TOKEN.encode()).hexdigest(),
    )


def context(**overrides):
    values = dict(
        tenant_id=2,
        public_id=CONTEXT_ID,
        purpose_code=CATALOG_CONTEXT_PURPOSE,
        effective_from=NOW - timedelta(minutes=1),
        expires_at=None,
        ended_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def binding(**overrides):
    values = dict(
        binding_ref=BINDING_ID,
        binding_version=1,
        merchant_public_id=MERCHANT_ID,
        location_public_id=LOCATION_ID,
        tenant_id=2,
        catalog_public_id=CATALOG_ID,
        price_code="retail",
        currency="XAF",
        scope_type="location",
        scope_id=1,
        effective_from=NOW - timedelta(minutes=1),
        effective_to=None,
        enabled=True,
    )
    values.update(overrides)
    return CatalogReadBinding(**values)


class FakeInteraction:
    def __init__(self, value):
        self.value = value

    def context_binding_by_public_id(self, public_id):
        assert public_id == CONTEXT_ID
        return self.value


class FakeBindingRepo:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def resolve(self, merchant_public_id, location_public_id, effective_at):
        return self.rows


class FakeRepo:
    def operational_merchant(self, tenant_id):
        assert tenant_id == 2
        return MERCHANT_ID

    def resource(self, tenant_id, public_id):
        if public_id not in {TABLE_ID, AREA_ID}:
            return None
        return SimpleNamespace(
            tenant_id=tenant_id,
            location_id=1,
            lifecycle_status="active",
        )


class FakeR1Repo:
    def resource_profile(self, tenant_id, public_id):
        if public_id == TABLE_ID:
            return SimpleNamespace(
                role=ResourceRole.TABLE,
                parent_resource_public_id=AREA_ID,
                service_mode_codes=("dine_in",),
            )
        if public_id == AREA_ID:
            return SimpleNamespace(
                role=ResourceRole.DINING_AREA,
                parent_resource_public_id=None,
                service_mode_codes=("dine_in",),
            )
        return None


class FakeR1:
    def modes(self, tenant_id):
        assert tenant_id == 2
        return (
            ServiceMode(UUID(int=11), 2, "dine_in", "Dine in", True, True, False, False, False, True),
            ServiceMode(UUID(int=12), 2, "takeaway", "Takeaway", False, False, False, False, True, True),
            ServiceMode(UUID(int=13), 2, "delivery", "Delivery", False, False, False, False, True, False),
        )


class FakeStructure:
    def resolve(self, *, tenant_id, location_id):
        assert (tenant_id, location_id) == (2, 1)
        return SimpleNamespace(
            tenant=SimpleNamespace(id=2),
            location=SimpleNamespace(
                id=1,
                public_id=LOCATION_ID,
                tenant_id=2,
                name="Wine & Dine · Main Branch",
                active=True,
            ),
        )


def transport(*, ctx=None, rows=None):
    adapters = SimpleNamespace(
        interaction=FakeInteraction(ctx or context()),
        repo=FakeRepo(),
        r1_repo=FakeR1Repo(),
        r1=FakeR1(),
        structure=FakeStructure(),
    )
    return CatalogReadTransport(
        adapters=adapters,
        binding_repository=FakeBindingRepo((binding(),) if rows is None else rows),
    )


def kwargs(**overrides):
    values = dict(
        context_binding_ref=CONTEXT_ID,
        merchant_public_id=MERCHANT_ID,
        location_public_id=LOCATION_ID,
        table_ref=None,
        dining_area_ref=None,
        purpose="merchant_discovery",
        effective_at=NOW,
        raw_token=TOKEN,
        principal=CATALOG_READ_PRINCIPAL,
        scopes=CATALOG_READ_SCOPE,
        correlation_ref="r4-local",
    )
    values.update(overrides)
    return values


def code(fn):
    with pytest.raises(CatalogReadError) as exc:
        fn()
    return exc.value.code


def test_minimal_attestation_regression_is_unchanged():
    result = transport().attest_context(
        context_binding_ref=CONTEXT_ID,
        effective_at=NOW,
        raw_token=TOKEN,
        principal=CATALOG_READ_PRINCIPAL,
        scopes=CATALOG_READ_SCOPE,
        correlation_ref="minimal",
    )
    assert result == {
        "context_binding_ref": str(CONTEXT_ID),
        "tenant_id": 2,
        "purpose_code": CATALOG_CONTEXT_PURPOSE,
        "effective_at": NOW.isoformat(),
        "expires_at": None,
    }


def test_merchant_discovery_rich_projection_is_server_verified():
    result = transport().attest_rich_context(**kwargs())
    assert result["tenant_ref"] == "2"
    assert result["merchant_ref"] == str(MERCHANT_ID)
    assert result["location_ref"] == str(LOCATION_ID)
    assert result["table_ref"] is None
    assert result["dining_area_ref"] is None
    assert result["purpose"] == "merchant_discovery"
    assert result["context_binding_ref"] == str(CONTEXT_ID)
    assert result["projection"] == {
        "merchant_ref": str(MERCHANT_ID),
        "location_ref": str(LOCATION_ID),
        "service_available": True,
        "display_name": "Wine & Dine · Main Branch",
        "terminology": [],
        "currency": "XAF",
        "allowed_fulfillment_modes": ["dine_in", "takeaway"],
    }


def test_dine_in_requires_and_validates_table_and_area():
    assert code(lambda: transport().attest_rich_context(
        **kwargs(purpose="dine_in")
    )) == "CATALOG_REQUEST_INVALID"
    result = transport().attest_rich_context(
        **kwargs(
            purpose="dine_in",
            table_ref=TABLE_ID,
            dining_area_ref=AREA_ID,
        )
    )
    assert result["table_ref"] == str(TABLE_ID)
    assert result["dining_area_ref"] == str(AREA_ID)


def test_non_dine_in_does_not_accept_table_context():
    assert code(lambda: transport().attest_rich_context(
        **kwargs(purpose="takeaway", table_ref=TABLE_ID)
    )) == "CATALOG_REQUEST_INVALID"


def test_unknown_entry_purpose_fails_closed():
    assert code(lambda: transport().attest_rich_context(
        **kwargs(purpose="checkout")
    )) == "CATALOG_REQUEST_INVALID"


def test_checkout_ia0_purpose_is_not_entry_purpose_mapping():
    bad = context(purpose_code="dine_in")
    assert code(lambda: transport(ctx=bad).attest_rich_context(
        **kwargs()
    )) == "CATALOG_CONTEXT_REQUIRED"


def test_merchant_location_and_tenant_mismatches_fail_closed():
    assert code(lambda: transport(rows=(binding(
        merchant_public_id=UUID(int=901)
    ),)).attest_rich_context(**kwargs())) == "CATALOG_BINDING_MISMATCH"
    assert code(lambda: transport(rows=(binding(
        location_public_id=UUID(int=902)
    ),)).attest_rich_context(**kwargs())) == "CATALOG_BINDING_MISMATCH"
    assert code(lambda: transport(rows=(binding(
        tenant_id=3
    ),)).attest_rich_context(**kwargs())) == "CATALOG_BINDING_MISMATCH"


def test_expired_context_fails_closed():
    expired = context(expires_at=NOW - timedelta(seconds=1))
    assert code(lambda: transport(ctx=expired).attest_rich_context(
        **kwargs()
    )) == "CATALOG_CONTEXT_REQUIRED"


def test_inactive_service_mode_is_not_advertised_or_accepted():
    result = transport().attest_rich_context(**kwargs())
    assert result["projection"]["allowed_fulfillment_modes"] == ["dine_in", "takeaway"]
    assert code(lambda: transport().attest_rich_context(
        **kwargs(purpose="delivery")
    )) == "CATALOG_ENTRY_PURPOSE_UNAVAILABLE"


def test_route_accepts_exact_65cb_rich_shape(monkeypatch):
    expected = transport().attest_rich_context(**kwargs())

    class CapturingTransport:
        def __init__(self, db):
            assert db == "dummy-db"

        def attest_rich_context(self, **values):
            assert values["context_binding_ref"] == CONTEXT_ID
            assert values["merchant_public_id"] == MERCHANT_ID
            assert values["location_public_id"] == LOCATION_ID
            assert values["table_ref"] is None
            assert values["dining_area_ref"] is None
            assert values["purpose"] == "merchant_discovery"
            assert values["effective_at"] == NOW
            return expected

    monkeypatch.setattr(router_module, "CatalogReadTransport", CapturingTransport)

    app = FastAPI()
    app.include_router(router_module.router)

    def fake_db():
        yield "dummy-db"

    app.dependency_overrides[get_db] = fake_db
    client = TestClient(app)
    response = client.post(
        "/internal/customer-channel/v1/context-attestations",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Service-Principal": CATALOG_READ_PRINCIPAL,
            "X-Service-Scopes": CATALOG_READ_SCOPE,
            "X-Correlation-Ref": "r4-route",
        },
        json={
            "schema": RICH_CONTEXT_SCHEMA,
            "context_binding_ref": str(CONTEXT_ID),
            "merchant_ref": str(MERCHANT_ID),
            "location_ref": str(LOCATION_ID),
            "table_ref": None,
            "dining_area_ref": None,
            "purpose": "merchant_discovery",
            "effective_at": NOW.isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json() == expected


def test_route_rejects_unknown_rich_schema(monkeypatch):
    app = FastAPI()
    app.include_router(router_module.router)

    def fake_db():
        yield "dummy-db"

    app.dependency_overrides[get_db] = fake_db
    client = TestClient(app)
    response = client.post(
        "/internal/customer-channel/v1/context-attestations",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Service-Principal": CATALOG_READ_PRINCIPAL,
            "X-Service-Scopes": CATALOG_READ_SCOPE,
            "X-Correlation-Ref": "r4-schema",
        },
        json={
            "schema": "unknown.schema",
            "context_binding_ref": str(CONTEXT_ID),
            "merchant_ref": str(MERCHANT_ID),
            "location_ref": str(LOCATION_ID),
            "table_ref": None,
            "dining_area_ref": None,
            "purpose": "merchant_discovery",
            "effective_at": NOW.isoformat(),
        },
    )
    assert response.status_code == 422
