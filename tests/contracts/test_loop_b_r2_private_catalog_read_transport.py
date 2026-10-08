from __future__ import annotations

import hashlib
import json
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
from restaurant.r2.contracts import (
    MenuEntryProjection,
    MenuPricingContext,
    MenuProjection,
    MenuSectionProjection,
    TargetType,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
TOKEN = "synthetic-catalog-reader-token"
CATALOG_ID = UUID("00000000-0000-0000-0000-000000000301")
MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000302")
LOCATION_ID = UUID("00000000-0000-0000-0000-000000000303")
CONTEXT_ID = UUID("00000000-0000-0000-0000-000000000304")
BINDING_ID = UUID("00000000-0000-0000-0000-000000000305")


@pytest.fixture(autouse=True)
def catalog_auth(monkeypatch):
    monkeypatch.setenv(
        CATALOG_TOKEN_DIGEST_CURRENT_ENV,
        hashlib.sha256(TOKEN.encode("utf-8")).hexdigest(),
    )
    monkeypatch.delenv(CATALOG_TOKEN_DIGEST_NEXT_ENV, raising=False)


def context(*, tenant_id: int = 2, expires_at=None):
    return SimpleNamespace(
        tenant_id=tenant_id,
        public_id=CONTEXT_ID,
        purpose_code=CATALOG_CONTEXT_PURPOSE,
        effective_from=NOW - timedelta(minutes=1),
        expires_at=expires_at,
        ended_at=None,
    )


def binding(**overrides):
    values = dict(
        binding_ref=BINDING_ID,
        binding_version=7,
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


class FakeBindingRepository:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = []

    def resolve(self, merchant_public_id, location_public_id, effective_at):
        self.calls.append((merchant_public_id, location_public_id, effective_at))
        return self.rows
class FakeR2:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def menu(self, *args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("synthetic semantic failure")
        section_id = UUID("00000000-0000-0000-0000-000000000401")
        entry_id = UUID("00000000-0000-0000-0000-000000000402")
        target_id = UUID("00000000-0000-0000-0000-000000000403")
        price_id = UUID("00000000-0000-0000-0000-000000000404")
        entry = MenuEntryProjection(
            entry_id,
            TargetType.ATOMIC_UNIT,
            target_id,
            {"public_id": str(target_id), "display_name": "Synthetic Item"},
            {"public_id": str(price_id), "amount": "1000", "currency": "XAF"},
            (),
            0,
        )
        section = MenuSectionProjection(section_id, "main", "Main", 0, (entry,))
        pricing = MenuPricingContext("retail", "XAF", "location", 1)
        return MenuProjection(
            2,
            {"public_id": str(CATALOG_ID)},
            args[2],
            pricing,
            (section,),
            False,
        )
def transport(rows=(None,), *, context_value=None, r2=None):
    actual_rows = () if rows == (None,) else rows
    fake_r2 = r2 or FakeR2()
    adapters = SimpleNamespace(
        interaction=FakeInteraction(context_value or context()),
        r2=fake_r2,
    )
    repo = FakeBindingRepository(actual_rows)
    return CatalogReadTransport(
        adapters=adapters,
        binding_repository=repo,
    ), repo, fake_r2


def auth_kwargs():
    return dict(
        raw_token=TOKEN,
        principal=CATALOG_READ_PRINCIPAL,
        scopes=CATALOG_READ_SCOPE,
        correlation_ref="corr-1",
    )


def error_code(fn):
    with pytest.raises(CatalogReadError) as exc:
        fn()
    return exc.value.code


def menu_call(service, **overrides):
    values = dict(
        context_binding_ref=CONTEXT_ID,
        merchant_public_id=MERCHANT_ID,
        location_public_id=LOCATION_ID,
        binding_ref=BINDING_ID,
        binding_version=7,
        effective_at=NOW,
        **auth_kwargs(),
    )
    values.update(overrides)
    return service.menu(**values)


def test_private_route_only():
    source = (ROOT / "restaurant" / "customer_channel" / "router.py").read_text(
        encoding="utf-8"
    )
    assert '@router.post("/context-attestations")' in source
    assert '@router.post("/catalog-bindings/resolve")' in source
    assert '@router.post("/catalog/menu")' in source
    assert 'PRIVATE_ROUTE_PREFIX = "/internal/customer-channel/v1"' in (
        ROOT / "restaurant" / "customer_channel" / "contracts.py"
    ).read_text(encoding="utf-8")
    assert '@router.get("/catalog' not in source


def test_auth_required():
    service, _, r2 = transport((binding(),))
    code = error_code(
        lambda: service.attest_context(
            context_binding_ref=CONTEXT_ID,
            effective_at=NOW,
            raw_token=None,
            principal=CATALOG_READ_PRINCIPAL,
            scopes=CATALOG_READ_SCOPE,
            correlation_ref="corr-1",
        )
    )
    assert code == "CATALOG_AUTH_REQUIRED"
    assert r2.calls == []


def test_wrong_principal_fails():
    service, _, r2 = transport((binding(),))
    code = error_code(
        lambda: service.attest_context(
            context_binding_ref=CONTEXT_ID,
            effective_at=NOW,
            raw_token=TOKEN,
            principal="wrong-principal",
            scopes=CATALOG_READ_SCOPE,
            correlation_ref="corr-1",
        )
    )
    assert code == "CATALOG_AUTH_FORBIDDEN"
    assert r2.calls == []


def test_write_scope_not_granted():
    service, _, r2 = transport((binding(),))
    code = error_code(
        lambda: service.attest_context(
            context_binding_ref=CONTEXT_ID,
            effective_at=NOW,
            raw_token=TOKEN,
            principal=CATALOG_READ_PRINCIPAL,
            scopes=CATALOG_READ_SCOPE + " restaurant.order.write",
            correlation_ref="corr-1",
        )
    )
    assert code == "CATALOG_AUTH_FORBIDDEN"
    assert r2.calls == []


def test_context_binding_required():
    service, _, r2 = transport((binding(),), context_value=SimpleNamespace(
        tenant_id=2,
        public_id=CONTEXT_ID,
        purpose_code=CATALOG_CONTEXT_PURPOSE,
        effective_from=NOW - timedelta(minutes=1),
        expires_at=NOW - timedelta(seconds=1),
        ended_at=None,
    ))
    code = error_code(
        lambda: service.attest_context(
            context_binding_ref=CONTEXT_ID,
            effective_at=NOW,
            **auth_kwargs(),
        )
    )
    assert code == "CATALOG_CONTEXT_REQUIRED"
    assert r2.calls == []


def test_missing_binding_fails_closed():
    service, _, r2 = transport(())
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_BINDING_MISSING"
    assert r2.calls == []
def test_multiple_binding_fails_closed():
    service, _, r2 = transport((binding(), binding(binding_ref=UUID(int=999))))
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_BINDING_AMBIGUOUS"
    assert r2.calls == []


def test_stale_binding_fails_closed():
    service, _, r2 = transport((binding(enabled=False),))
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_BINDING_STALE"
    assert r2.calls == []


def test_binding_version_mismatch_fails_closed():
    service, _, r2 = transport((binding(),))
    code = error_code(lambda: menu_call(service, binding_version=8))
    assert code == "CATALOG_BINDING_VERSION_MISMATCH"
    assert r2.calls == []


def test_tenant_mismatch_fails_closed():
    service, _, r2 = transport((binding(tenant_id=3),))
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_BINDING_MISMATCH"
    assert r2.calls == []


def test_binding_resolution_uses_exact_key():
    service, repo, _ = transport((binding(),))
    result = service.resolve_binding(
        context_binding_ref=CONTEXT_ID,
        merchant_public_id=MERCHANT_ID,
        location_public_id=LOCATION_ID,
        effective_at=NOW,
        **auth_kwargs(),
    )
    assert repo.calls == [(MERCHANT_ID, LOCATION_ID, NOW)]
    assert result["binding_ref"] == str(BINDING_ID)
    assert result["binding_version"] == 7
    assert result["catalog_public_id"] == str(CATALOG_ID)


def test_menu_forwards_exact_seven_fields_and_calls_r2_once():
    service, _, r2 = transport((binding(),))
    menu_call(service)
    assert len(r2.calls) == 1
    assert r2.calls[0] == (
        2,
        CATALOG_ID,
        NOW,
        "retail",
        "XAF",
        "location",
        1,
    )
    assert BINDING_ID not in r2.calls[0]
    assert 7 not in r2.calls[0]
    assert "corr-1" not in r2.calls[0]


def test_menu_projection_identities_and_resolved_price_preserved():
    service, _, _ = transport((binding(),))
    result = menu_call(service)
    assert result["tenant_id"] == 2
    assert result["catalog_reference"]["public_id"] == str(CATALOG_ID)
    section = result["sections"][0]
    entry = section["entries"][0]
    assert section["section_public_id"] == "00000000-0000-0000-0000-000000000401"
    assert entry["catalog_entry_public_id"] == "00000000-0000-0000-0000-000000000402"
    assert entry["target_public_id"] == "00000000-0000-0000-0000-000000000403"
    assert entry["resolved_price"]["public_id"] == "00000000-0000-0000-0000-000000000404"
    assert entry["resolved_price"]["amount"] == "1000"
    assert result["creates_financial_truth"] is False


def test_retry_preserves_exact_effective_at_value():
    service, _, r2 = transport((binding(),))
    first = menu_call(service)
    second = menu_call(service)
    assert len(r2.calls) == 2
    assert r2.calls[0][2] is NOW
    assert r2.calls[1][2] is NOW
    assert first["effective_at"] == second["effective_at"]


def test_auth_failure_is_not_forwarded_or_retried():
    service, _, r2 = transport((binding(),))
    code = error_code(
        lambda: menu_call(service, principal="wrong-principal")
    )
    assert code == "CATALOG_AUTH_FORBIDDEN"
    assert r2.calls == []


def test_semantic_failure_is_not_retried():
    failing_r2 = FakeR2(fail=True)
    service, _, _ = transport((binding(),), r2=failing_r2)
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_SEMANTIC_FAILURE"
    assert len(failing_r2.calls) == 1


def test_default_binding_adapter_fails_closed():
    adapters = SimpleNamespace(
        interaction=FakeInteraction(context()),
        r2=FakeR2(),
    )
    service = CatalogReadTransport(adapters=adapters)
    code = error_code(lambda: menu_call(service))
    assert code == "CATALOG_BINDING_MISSING"
    assert adapters.r2.calls == []


def test_next_digest_slot_is_supported(monkeypatch):
    next_token = "synthetic-next-token"
    monkeypatch.setenv(CATALOG_TOKEN_DIGEST_CURRENT_ENV, "0" * 64)
    monkeypatch.setenv(
        CATALOG_TOKEN_DIGEST_NEXT_ENV,
        hashlib.sha256(next_token.encode("utf-8")).hexdigest(),
    )
    service, _, _ = transport((binding(),))
    result = service.attest_context(
        context_binding_ref=CONTEXT_ID,
        effective_at=NOW,
        raw_token=next_token,
        principal=CATALOG_READ_PRINCIPAL,
        scopes=CATALOG_READ_SCOPE,
        correlation_ref="corr-next",
    )
    assert result["context_binding_ref"] == str(CONTEXT_ID)
def load_transport_contract():
    path = ROOT / "contracts" / "restaurant" / "v1" / "loop_b_r2_private_catalog_read_transport.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_transport_contract_freezes_private_auth_and_retry_law():
    contract = load_transport_contract()
    assert contract["visibility"] == "private_service_to_private_service"
    assert contract["public_internet_surface"] is False
    assert contract["authentication"]["principal"] == CATALOG_READ_PRINCIPAL
    assert contract["authentication"]["required_scopes"] == [CATALOG_READ_SCOPE]
    retry = contract["retry"]
    assert retry["connect_timeout_seconds"] == 1
    assert retry["read_timeout_seconds"] == 3
    assert retry["max_retry_count"] == 1
    assert retry["total_attempts_max"] == 2
    assert retry["backoff_milliseconds"] == 100
    assert retry["preserve_serialized_effective_at"] is True
    assert "auth_failure" in retry["nonretryable"]
    assert "authorization_failure" in retry["nonretryable"]
    assert "semantic_mismatch" in retry["nonretryable"]


def test_contract_forbids_repricing_and_business_effects():
    contract = load_transport_contract()
    menu = contract["menu"]
    assert menu["authority"] == "R2Authority.menu"
    assert menu["repricing"] is False
    assert menu["direct_catalog_table_bypass"] is False
    assert menu["order_effect"] is False
    assert menu["payment_effect"] is False
    assert menu["inventory_effect"] is False
    assert menu["forwarded_inputs"] == [
        "tenant_id",
        "catalog_public_id",
        "effective_at",
        "price_code",
        "currency",
        "scope_type",
        "scope_id",
    ]
    assert menu["not_forwarded_as_business_inputs"] == [
        "binding_ref",
        "binding_version",
        "correlation_ref",
    ]
    effects = contract["effects"]
    assert effects["real_network_calls"] == 0
    assert effects["deployment"] == 0
    assert effects["order_creation"] == 0
    assert effects["payment_creation"] == 0
    assert effects["inventory_mutation"] == 0
    assert effects["financial_effect"] == "zero"
