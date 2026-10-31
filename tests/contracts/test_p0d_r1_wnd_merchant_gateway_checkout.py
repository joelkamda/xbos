from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_contract import (
    PaymentCommandIdempotencyConflict,
)
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.integrations.xafpay_v2.contract import XafPayV2CheckoutResponse
from core.integrations.xafpay_v2.repository import AttemptAuthority
from core.integrations.xafpay_v2.service import XafPayV2Service
from core.integrations.xafpay_v2.wnd_service import WndXafPayV2Service
from restaurant.c3.service import (
    finance_correlation_id,
    payment_attempt_public_id,
    payment_intent_public_id,
    payment_request_public_id,
)
from restaurant.customer_channel.contracts import H1BError, TrustedCheckoutScope
from restaurant.customer_channel.gateway_checkout_bridge import (
    VerifiedGatewayMerchantBinding,
    WNDGatewayCheckoutBridge,
)

TENANT = 2
ORG = 1
BRANCH = 1
LOCATION = 1
LOCATION_PUBLIC = UUID("20000000-0000-4000-8000-000000000105")
ORDER = UUID("20000000-0000-4000-8000-000000000101")
MERCHANT = UUID("20000000-0000-4000-8000-000000000102")
CONTEXT = UUID("20000000-0000-4000-8000-000000000103")
SERVICE_ID = UUID("20000000-0000-4000-8000-000000000104")
GW_MERCHANT = "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c"
CREDENTIAL_REF = "8af0fbaf-024b-4ab8-9f99-117a74e952c7"
CHECKOUT = "chk_018d6f5a-3333-7333-8333-333333333333"
SUBMITTED_AT = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def scope(**changes):
    values = {
        "tenant_id": TENANT,
        "branch_id": BRANCH,
        "organization_unit_id": ORG,
        "location_id": LOCATION,
        "merchant_public_id": MERCHANT,
        "context_binding_public_id": CONTEXT,
        "service_identity_public_id": SERVICE_ID,
        "currency": "XAF",
        "correlation_ref": "p0d-wnd-commercial",
    }
    values.update(changes)
    return TrustedCheckoutScope(**values)


def binding(**changes):
    values = {
        "tenant_id": TENANT,
        "merchant_public_id": MERCHANT,
        "gateway_merchant_id": GW_MERCHANT,
        "service_credential_reference": CREDENTIAL_REF,
        "verification_state": "verified",
    }
    values.update(changes)
    return VerifiedGatewayMerchantBinding(**values)


class FakeR1Repo:
    def __init__(self):
        self.order_value = SimpleNamespace(
            public_id=ORDER,
            tenant_id=TENANT,
            status=SimpleNamespace(value="submitted"),
            submitted_at=SUBMITTED_AT,
            row_version=7,
            order_code="WND-P0D-001",
        )

    def order(self, tenant_id, order_ref):
        if tenant_id == TENANT and UUID(str(order_ref)) == ORDER:
            return self.order_value
        return None


class FakeAuthority:
    def __init__(self):
        self.adapters = SimpleNamespace(r1_repo=FakeR1Repo())
        self.repo = SimpleNamespace(
            location_public_id=lambda tenant_id, location_id: LOCATION_PUBLIC,
            draft_by_order=lambda tenant_id, order_ref: {
                "tenant_id": TENANT,
                "organization_unit_id": ORG,
                "location_id": LOCATION,
                "merchant_public_id": MERCHANT,
                "context_binding_public_id": CONTEXT,
                "order_public_id": ORDER,
                "catalog_binding_version": 4,
            },
        )
        self.calls = 0

    def create_payment_request(self, *, scope, order_ref):
        self.calls += 1
        request_ref = payment_request_public_id(
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            order_public_id=UUID(str(order_ref)),
            row_version=7,
        )
        correlation = finance_correlation_id(
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            order_public_id=UUID(str(order_ref)),
            row_version=7,
        )
        return {
            "payment_request_ref": str(request_ref),
            "order_ref": str(order_ref),
            "merchant_reference": "WND-P0D-001",
            "correlation_ref": str(correlation),
            "canonical_amount": Decimal(3500),
            "currency": "XAF",
            "permitted_methods": ["pay_at_counter", "mtn_mobile_money", "orange_money"],
            "policy_ref": "wnd.payments.enabled_methods@3",
            "expires_at": None,
            "payment_request_state": "open",
            "wallet_handoff_context": None,
            "safe_next_action": "choose_payment_method",
            "receipt_ref": None,
        }


class FakeRepository:
    def __init__(self):
        self.attempts = {}
        self.settlements = {}
        self.bind_calls = []

    def attempt_authority(self, session, attempt_public_id, *, lock=False):
        del session, lock
        return self.attempts.get(UUID(str(attempt_public_id)))

    def settlement_count_for_attempt(self, session, *, tenant_id, attempt_public_id):
        del session
        assert tenant_id == TENANT
        return self.settlements.get(UUID(str(attempt_public_id)), 0)

    def bind_checkout_session(
        self, session, attempt, *, checkout_session_id, checkout_status
    ):
        del session
        metadata = dict(attempt.metadata)
        existing = metadata.get("checkout_session_id")
        if existing and existing != checkout_session_id:
            raise RuntimeError("XAFPAY_CHECKOUT_SESSION_IDENTITY_CONFLICT")
        metadata["checkout_session_id"] = checkout_session_id
        metadata["checkout_status"] = checkout_status
        updated = replace(attempt, metadata=metadata, row_version=attempt.row_version + 1)
        self.attempts[attempt.public_id] = updated
        self.bind_calls.append((attempt.public_id, checkout_session_id, checkout_status))
        return updated


class FakeClient:
    def __init__(self, status="CREATED"):
        self.status = status
        self.requests = []

    def create_checkout(self, request):
        self.requests.append(request)
        return XafPayV2CheckoutResponse(
            checkout_session_id=CHECKOUT,
            external_reference=request.external_reference,
            status=self.status,
            amount_minor=int(request.amount),
            currency_code="XAF",
            public_token=None if self.status == "EXPIRED" else "chkpub_p0d_wnd_staging",
            presentation_state=(
                "PRESENTATION_EXPIRED" if self.status == "EXPIRED" else "PRESENTABLE"
            ),
            evidence={
                "merchant": {"display_name": "WND"},
                "environment": "offline-staging-contract",
            },
        )


@pytest.fixture()
def canonical_finance(monkeypatch):
    repo = FakeRepository()
    intents = {}

    def create_intent(session, command):
        del session
        existing = intents.get(command.public_id)
        fingerprint = (
            command.tenant_id,
            command.organization_unit_id,
            command.payment_request_public_id,
            command.requested_amount,
            command.currency_code,
            command.idempotency_key,
        )
        if existing is not None:
            if existing[0] != fingerprint:
                raise RuntimeError("fake_intent_idempotency_conflict")
            return SimpleNamespace(payment_intent=existing[1], replayed=True)
        record = SimpleNamespace(
            public_id=command.public_id,
            requested_amount=command.requested_amount,
            currency_code=command.currency_code,
            metadata=dict(command.metadata),
        )
        intents[command.public_id] = (fingerprint, record)
        return SimpleNamespace(payment_intent=record, replayed=False)

    def create_attempt(session, command):
        del session
        existing = repo.attempts.get(command.public_id)
        if existing is not None:
            command_metadata = dict(command.metadata)
            existing_command_metadata = {
                key: existing.metadata.get(key) for key in command_metadata
            }
            if (
                existing.attempted_amount != command.attempted_amount
                or existing.payment_rail_code != command.payment_rail_code
                or existing_command_metadata != command_metadata
            ):
                raise RuntimeError("fake_attempt_idempotency_conflict")
            return SimpleNamespace(payment_attempt=existing, replayed=True)
        record = AttemptAuthority(
            id=1,
            public_id=command.public_id,
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            payment_intent_public_id=command.payment_intent_public_id,
            payment_tender_public_id=command.payment_tender_public_id,
            attempt_state="pending",
            attempted_amount=command.attempted_amount,
            currency_code=command.currency_code,
            payment_method_code=command.payment_method_code,
            payment_rail_code=command.payment_rail_code,
            orchestrator_code=command.orchestrator_code,
            provider_account_id=None,
            underlying_provider_code=None,
            external_attempt_reference=None,
            occurred_at=command.occurred_at,
            business_date=command.business_date,
            calendar_policy_version=command.calendar_policy_version,
            correlation_id=command.correlation_id,
            row_version=1,
            metadata=dict(command.metadata),
        )
        repo.attempts[record.public_id] = record
        return SimpleNamespace(payment_attempt=record, replayed=False)

    monkeypatch.setattr(XafPayV2Service, "repository", repo)
    monkeypatch.setattr(TransactionalPaymentIntentEngine, "create_intent", create_intent)
    monkeypatch.setattr(TransactionalPaymentAttemptEngine, "create", create_attempt)
    return repo, intents


def _expected_request_ref():
    return payment_request_public_id(
        tenant_id=TENANT,
        organization_unit_id=ORG,
        order_public_id=ORDER,
        row_version=7,
    )


def test_verified_binding_never_accepts_a_credential_secret():
    with pytest.raises(ValueError, match="MUST_NOT_CONTAIN_CREDENTIAL_SECRET"):
        binding(service_credential_reference="xps_staging_abc.secret")


def test_unverified_binding_holds_before_payment_request(canonical_finance):
    authority = FakeAuthority()
    with pytest.raises(H1BError) as exc:
        WNDGatewayCheckoutBridge.initiate(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            selected_method="mtn_mobile_money",
            binding=binding(verification_state="candidate"),
            client=FakeClient(),
        )
    assert exc.value.code == "PAYMENT_OPTIONS_UNAVAILABLE"
    assert authority.calls == 0


@pytest.mark.parametrize(
    "bad_binding",
    [
        binding(tenant_id=99),
        binding(merchant_public_id=UUID("20000000-0000-4000-8000-000000000999")),
    ],
)
def test_wrong_tenant_or_merchant_binding_fails_before_finance(canonical_finance, bad_binding):
    authority = FakeAuthority()
    with pytest.raises(H1BError) as exc:
        WNDGatewayCheckoutBridge.initiate(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            selected_method="mtn_mobile_money",
            binding=bad_binding,
            client=FakeClient(),
        )
    assert exc.value.code == "CONTEXT_MISMATCH"
    assert authority.calls == 0


@pytest.mark.parametrize(
    "field,other_scope",
    [
        ("tenant_id", 9999),
        ("organization_unit_id", 9999),
        ("location_id", 9999),
        ("merchant_public_id", UUID("20000000-0000-4000-8000-000000000999")),
        ("context_binding_public_id", UUID("20000000-0000-4000-8000-000000000998")),
        ("order_public_id", UUID("20000000-0000-4000-8000-000000000997")),
    ],
)
def test_checkout_rejects_draft_owned_by_another_scope_before_payment_request(
    canonical_finance, field, other_scope
):
    authority = FakeAuthority()
    original_draft = authority.repo.draft_by_order(TENANT, ORDER)
    authority.repo.draft_by_order = lambda _tenant, _order: {
        **original_draft,
        field: other_scope,
    }
    client = FakeClient()
    with pytest.raises(H1BError) as exc:
        WNDGatewayCheckoutBridge.initiate(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            selected_method="mtn_mobile_money",
            binding=binding(),
            client=client,
        )
    assert exc.value.code == "CONTEXT_MISMATCH"
    assert authority.calls == 0
    assert client.requests == []


def test_canonical_order_to_hosted_checkout_reuses_c3_c4_identities(canonical_finance):
    repo, _ = canonical_finance
    authority = FakeAuthority()
    client = FakeClient()

    first = WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=client,
    )
    second = WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=client,
    )

    request_ref = _expected_request_ref()
    intent_ref = payment_intent_public_id(request_ref)
    attempt_ref = payment_attempt_public_id(request_ref)

    assert first["payment_request_ref"] == second["payment_request_ref"] == str(request_ref)
    assert first["payment_attempt_ref"] == second["payment_attempt_ref"] == str(attempt_ref)
    assert first["canonical_amount"] == second["canonical_amount"] == Decimal(3500)
    assert first["currency"] == "XAF"
    assert first["checkout_session_id"] == second["checkout_session_id"] == CHECKOUT
    assert first["checkout_token"] == "chkpub_p0d_wnd_staging"
    assert first["payment_status"] == "PAYMENT_PENDING"
    assert first["paid"] is False
    assert first["can_fulfill"] is False

    attempt = repo.attempts[attempt_ref]
    assert attempt.payment_intent_public_id == intent_ref
    assert attempt.payment_tender_public_id is None
    assert attempt.metadata["order_public_id"] == str(ORDER)
    assert attempt.metadata["payment_request_public_id"] == str(request_ref)
    assert attempt.metadata["merchant_public_id"] == str(MERCHANT)
    assert attempt.metadata["gateway_merchant_id"] == GW_MERCHANT
    assert attempt.metadata["service_credential_reference"] == CREDENTIAL_REF
    assert attempt.metadata["wnd_location_public_id"] == str(LOCATION_PUBLIC)
    assert attempt.metadata["wnd_catalog_version"] == 4
    assert "xps_" not in str(attempt.metadata)
    assert len(client.requests) == 2
    assert client.requests[0].external_reference == client.requests[1].external_reference
    assert client.requests[0].external_reference == f"wnd:order:{ORDER}:r7"
    assert client.requests[0].idempotency_key == client.requests[1].idempotency_key
    assert client.requests[0].idempotency_key == f"wnd:checkout:{ORDER}:r7"
    assert client.requests[0].body() == {
        "external_reference": f"wnd:order:{ORDER}:r7",
        "amount": {"minor": 3500, "currency": "XAF"},
        "permitted_options": [{"method": "MOBILE_MONEY", "rail": "MTN_MOMO"}],
        "language": "fr",
        "branding": {"profile": "default"},
        "expires_in_seconds": 900,
        "channel": "wnd.whatsapp",
        "metadata": {
            "tenant_id": TENANT,
            "wnd_merchant_public_id": str(MERCHANT),
            "wnd_order_public_id": str(ORDER),
            "wnd_location_public_id": str(LOCATION_PUBLIC),
            "wnd_order_revision": 7,
            "wnd_catalog_version": 4,
        },
    }
    assert repo.settlements.get(attempt_ref, 0) == 0
    assert repo.bind_calls == []


def test_caller_cannot_choose_cash_for_hosted_external_checkout(canonical_finance):
    authority = FakeAuthority()
    client = FakeClient()
    with pytest.raises(H1BError) as exc:
        WNDGatewayCheckoutBridge.initiate(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            selected_method="pay_at_counter",
            binding=binding(),
            client=client,
        )
    assert exc.value.code == "UNSUPPORTED_METHOD"
    assert client.requests == []


def test_changed_amount_for_same_request_fails_before_second_checkout(canonical_finance):
    authority = FakeAuthority()
    client = FakeClient()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=client,
    )
    original = authority.create_payment_request

    def changed(*, scope, order_ref):
        result = original(scope=scope, order_ref=order_ref)
        result["canonical_amount"] = Decimal(3600)
        return result

    authority.create_payment_request = changed
    with pytest.raises(RuntimeError, match="idempotency_conflict"):
        WNDGatewayCheckoutBridge.initiate(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            selected_method="mtn_mobile_money",
            binding=binding(),
            client=client,
        )
    assert len(client.requests) == 1


def test_pending_status_is_never_paid_or_fulfillable(canonical_finance):
    authority = FakeAuthority()
    client = FakeClient()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="orange_money",
        binding=binding(),
        client=client,
    )
    result = WNDGatewayCheckoutBridge.status(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        binding=binding(),
    )
    assert result["payment_status"] == "PAYMENT_PENDING"
    assert result["paid"] is False
    assert result["can_fulfill"] is False
    assert result["checkout_status"] is None
    assert "gateway_merchant_id" not in result
    assert "service_credential_reference" not in result
    assert "gateway_payment_id" not in result


def test_succeeded_attempt_without_settlement_fails_closed(canonical_finance):
    repo, _ = canonical_finance
    authority = FakeAuthority()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=FakeClient(),
    )
    attempt_ref = payment_attempt_public_id(_expected_request_ref())
    current = repo.attempts[attempt_ref]
    repo.attempts[attempt_ref] = replace(current, attempt_state="succeeded")
    with pytest.raises(RuntimeError, match="SETTLEMENT_CARDINALITY"):
        WndXafPayV2Service.canonical_status(
            object(),
            tenant_id=TENANT,
            organization_unit_id=ORG,
            merchant_public_id=MERCHANT,
            gateway_merchant_id=GW_MERCHANT,
            service_credential_reference=CREDENTIAL_REF,
            order_public_id=ORDER,
            order_row_version=7,
            payment_request_public_id=_expected_request_ref(),
            location_public_id=LOCATION_PUBLIC,
            catalog_version=4,
        )


def test_exactly_one_confirmed_settlement_is_paid_authority(canonical_finance):
    repo, _ = canonical_finance
    authority = FakeAuthority()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=FakeClient(),
    )
    attempt_ref = payment_attempt_public_id(_expected_request_ref())
    current = repo.attempts[attempt_ref]
    repo.attempts[attempt_ref] = replace(
        current,
        attempt_state="succeeded",
        external_attempt_reference="pay_018d6f5a-3333-7333-8333-333333333333",
    )
    repo.settlements[attempt_ref] = 1

    customer = WNDGatewayCheckoutBridge.status(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        binding=binding(),
    )
    merchant = WNDGatewayCheckoutBridge.merchant_reconciliation(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        binding=binding(),
    )

    assert customer["payment_status"] == "PAYMENT_CONFIRMED"
    assert customer["paid"] is True
    assert customer["can_fulfill"] is True
    assert merchant["reconciliation_state"] == "CONFIRMED_MATCH"
    assert merchant["confirmed_settlements"] == 1
    assert merchant["gateway_merchant_id"] == GW_MERCHANT
    assert merchant["gateway_payment_id"].startswith("pay_")


@pytest.mark.parametrize("state", ["failed", "cancelled", "expired"])
def test_terminal_non_success_never_becomes_paid(canonical_finance, state):
    repo, _ = canonical_finance
    authority = FakeAuthority()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=FakeClient(),
    )
    attempt_ref = payment_attempt_public_id(_expected_request_ref())
    repo.attempts[attempt_ref] = replace(repo.attempts[attempt_ref], attempt_state=state)
    result = WNDGatewayCheckoutBridge.status(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        binding=binding(),
    )
    assert result["payment_status"] == "PAYMENT_NOT_CONFIRMED"
    assert result["paid"] is False
    assert result["can_fulfill"] is False


def test_metadata_binding_change_is_rejected_during_reconciliation(canonical_finance):
    repo, _ = canonical_finance
    authority = FakeAuthority()
    WNDGatewayCheckoutBridge.initiate(
        object(),
        authority=authority,
        scope=scope(),
        order_ref=ORDER,
        selected_method="mtn_mobile_money",
        binding=binding(),
        client=FakeClient(),
    )
    attempt_ref = payment_attempt_public_id(_expected_request_ref())
    current = repo.attempts[attempt_ref]
    changed = dict(current.metadata)
    changed["gateway_merchant_id"] = "mch_018d6f5a-9999-7999-8999-999999999999"
    repo.attempts[attempt_ref] = replace(current, metadata=changed)

    with pytest.raises(RuntimeError, match="CANONICAL_BINDING_CONFLICT"):
        WNDGatewayCheckoutBridge.merchant_reconciliation(
            object(),
            authority=authority,
            scope=scope(),
            order_ref=ORDER,
            binding=binding(),
        )


def test_checkout_runtime_is_feature_disabled_until_staging_injects_binding_and_client():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    router = (root / "restaurant/customer_channel/router.py").read_text(encoding="utf-8")
    block = router.split("def _gateway_checkout_runtime", 1)[1]
    assert "wnd_gateway_checkout_runtime" in block
    assert "PAYMENT_OPTIONS_UNAVAILABLE" in block
    assert "require_client" in block
    assert 'getattr(runtime, "binding", None)' in block
    assert 'getattr(runtime, "client", None)' in block

def test_hosted_checkout_source_does_not_reclassify_http_success_as_paid():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    bridge = (root / "restaurant/customer_channel/gateway_checkout_bridge.py").read_text(
        encoding="utf-8"
    )
    wnd = (root / "core/integrations/xafpay_v2/wnd_service.py").read_text(
        encoding="utf-8"
    )
    assert '"paid": False' in wnd
    assert '"can_fulfill": False' in wnd
    assert 'state == "succeeded"' in wnd
    canonical = wnd.split("def initiate_canonical_order", 1)[1]
    assert "bind_checkout_session(" not in canonical.split("def canonical_status", 1)[0]
    assert "settlements != 1" in wnd
    assert '"PAYMENT_CONFIRMED"' in wnd
    assert "service_credential_reference" in bridge
    assert "xps_" in bridge  # explicit secret-reference guard


def test_pg17_real_wnd_order_to_real_finance_rows_and_hosted_checkout_pending():
    import importlib.util
    import os
    from pathlib import Path

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from restaurant.customer_channel.draft_order import (
        CustomerChannelDraftOrderAuthority,
    )

    raw_url = os.environ.get("P0D_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("P0D_TEST_DATABASE_URL is required for the disposable PG17 integration")

    url = make_url(raw_url)
    assert url.host == "127.0.0.1"
    assert url.port == 55624
    assert url.database == "xbos_track_b_m13_adoption_test"
    assert url.username == "wnd_p0d_fixture"

    fixture_path = Path(__file__).with_name("test_wnd_demo_r1_isolated_order_pg17.py")
    spec = importlib.util.spec_from_file_location("p0d_wnd_fixture", fixture_path)
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)

    class PGFakeClient:
        def __init__(self):
            self.requests = []

        def create_checkout(self, request):
            self.requests.append(request)
            return XafPayV2CheckoutResponse(
                checkout_session_id=CHECKOUT,
                external_reference=request.external_reference,
                status="CREATED",
                amount_minor=int(request.amount),
                currency_code="XAF",
                public_token="chkpub_p0d_pg17",
                presentation_state="PRESENTABLE",
                evidence={"environment": "disposable-pg17"},
            )

    engine = create_engine(raw_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            fixture._seed(session)
            session.execute(
                text(
                    """
                    INSERT INTO currency_assets(
                        code,asset_kind,display_name,minor_unit_scale,
                        maximum_storage_scale,active
                    ) VALUES(
                        'XAF','fiat','Central African CFA franc',0,8,true
                    ) ON CONFLICT(code) DO NOTHING
                    """
                )
            )
            session.commit()
            before = fixture.AT - __import__("datetime").timedelta(days=1)
            session.execute(
                text(
                    """
                    INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active)
                    VALUES(1,:tenant,'P0D-1','P0D Synthetic Branch','Douala','offline-only',true)
                    """
                ),
                {"tenant": fixture.TENANT_ID},
            )
            session.execute(
                text(
                    """
                    INSERT INTO legacy_branch_structural_mappings(
                        tenant_id,branch_id,organization_unit_id,location_id
                    ) VALUES(:tenant,1,:org,:location)
                    """
                ),
                {
                    "tenant": fixture.TENANT_ID,
                    "org": fixture.ORG_ID,
                    "location": fixture.LOCATION_ID,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO configuration_definitions(
                        id,public_id,config_key,value_type,owner_code,
                        allowed_scopes,resolution_order,required,secret,
                        tenant_overridable,validation_constraints,lifecycle
                    ) VALUES(
                        910901,:public_id,'wnd.payments.enabled_methods','json','wnd',
                        ARRAY['tenant']::text[],ARRAY['tenant']::text[],true,false,
                        false,CAST('{}' AS jsonb),'active'
                    )
                    """
                ),
                {"public_id": str(fixture._u(41))},
            )
            session.execute(
                text(
                    """
                    INSERT INTO configuration_values(
                        id,public_id,definition_id,tenant_id,scope_type,scope_id,
                        effective_from,row_version,json_value
                    ) VALUES(
                        910902,:public_id,910901,:tenant,'tenant',:tenant,
                        :effective,3,CAST(:value AS jsonb)
                    )
                    """
                ),
                {
                    "public_id": str(fixture._u(42)),
                    "tenant": fixture.TENANT_ID,
                    "effective": before,
                    "value": '{"settlement_methods":["cash","mtn","orange"]}',
                },
            )
            session.commit()

            checkout_authority = CustomerChannelDraftOrderAuthority(session)
            trusted = TrustedCheckoutScope(
                fixture.TENANT_ID,
                1,
                fixture.ORG_ID,
                fixture.LOCATION_ID,
                fixture.MERCHANT_PUBLIC,
                fixture.CONTEXT_BINDING_PUBLIC,
                fixture.SERVICE_IDENTITY_PUBLIC,
                "XAF",
                "p0d-pg17-real-wnd-order",
            )
            created = checkout_authority.create_draft(
                scope=trusted,
                client_command_ref="p0d-pg17-create",
                service_mode="takeaway",
                contact_ref=fixture.CONTACT_BINDING_PUBLIC,
                at=fixture.AT,
            )
            session.commit()
            draft_ref = UUID(created["draft_ref"])
            order_ref = UUID(created["order_ref"])
            updated = checkout_authority.mutate_draft(
                scope=trusted,
                draft_ref=draft_ref,
                payload={
                    "operation": "ADD_LINE",
                    "client_command_ref": "p0d-pg17-add",
                    "expected_draft_version": created["draft_version"],
                    "item_ref": str(fixture.ENTRY_PUBLIC),
                    "quantity": "2",
                    "modifier_refs": [],
                },
                at=fixture.AT + __import__("datetime").timedelta(minutes=1),
            )
            session.commit()
            assert Decimal(updated["canonical_total"]) == Decimal(3500)
            confirmation = checkout_authority.confirm_draft(
                scope=trusted,
                draft_ref=draft_ref,
                at=fixture.AT + __import__("datetime").timedelta(minutes=2),
            )
            session.commit()
            submitted = checkout_authority.submit_draft(
                scope=trusted,
                draft_ref=draft_ref,
                confirmation_ref=confirmation.confirmation_ref,
                client_submit_ref="p0d-pg17-submit",
                at=fixture.AT + __import__("datetime").timedelta(minutes=3),
            )
            session.commit()
            assert submitted.order_ref == order_ref

            runtime_binding = VerifiedGatewayMerchantBinding(
                tenant_id=fixture.TENANT_ID,
                merchant_public_id=fixture.MERCHANT_PUBLIC,
                gateway_merchant_id="mch_018d6f5a-1111-7111-8111-111111111111",
                service_credential_reference="11111111-2222-4333-8444-555555555555",
                verification_state="verified",
            )
            client = PGFakeClient()
            first = WNDGatewayCheckoutBridge.initiate(
                session,
                authority=checkout_authority.checkout,
                scope=trusted,
                order_ref=order_ref,
                selected_method="mtn_mobile_money",
                binding=runtime_binding,
                client=client,
            )
            session.commit()
            second = WNDGatewayCheckoutBridge.initiate(
                session,
                authority=checkout_authority.checkout,
                scope=trusted,
                order_ref=order_ref,
                selected_method="mtn_mobile_money",
                binding=runtime_binding,
                client=client,
            )
            session.commit()

            assert first["order_ref"] == second["order_ref"] == str(order_ref)
            assert first["canonical_amount"] == second["canonical_amount"] == Decimal(3500)
            assert first["payment_attempt_ref"] == second["payment_attempt_ref"]
            assert first["checkout_session_id"] == second["checkout_session_id"] == CHECKOUT
            assert first["payment_status"] == "PAYMENT_PENDING"
            assert first["paid"] is False
            assert len(client.requests) == 2
            assert client.requests[0].idempotency_key == client.requests[1].idempotency_key
            assert client.requests[0].external_reference == client.requests[1].external_reference

            status = WNDGatewayCheckoutBridge.status(
                session,
                authority=checkout_authority.checkout,
                scope=trusted,
                order_ref=order_ref,
                binding=runtime_binding,
            )
            merchant = WNDGatewayCheckoutBridge.merchant_reconciliation(
                session,
                authority=checkout_authority.checkout,
                scope=trusted,
                order_ref=order_ref,
                binding=runtime_binding,
            )
            assert status["payment_status"] == "PAYMENT_PENDING"
            assert status["paid"] is False
            assert merchant["reconciliation_state"] == "PENDING_MATCH"
            assert merchant["confirmed_settlements"] == 0

            counts = session.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM canonical_payment_requests WHERE tenant_id=:tenant),
                      (SELECT count(*) FROM canonical_payment_intents WHERE tenant_id=:tenant),
                      (SELECT count(*) FROM canonical_payment_attempts WHERE tenant_id=:tenant),
                      (SELECT count(*) FROM payment_settlements WHERE tenant_id=:tenant)
                    """
                ),
                {"tenant": fixture.TENANT_ID},
            ).one()
            assert tuple(int(x) for x in counts) == (1, 1, 1, 0)

            order_row = session.execute(
                text(
                    """
                    SELECT lifecycle_status
                    FROM r1_restaurant_orders
                    WHERE tenant_id=:tenant AND public_id=:order_ref
                    """
                ),
                {"tenant": fixture.TENANT_ID, "order_ref": str(order_ref)},
            ).scalar_one()
            assert order_row == "submitted"

            with pytest.raises(PaymentCommandIdempotencyConflict):
                WNDGatewayCheckoutBridge.initiate(
                    session,
                    authority=checkout_authority.checkout,
                    scope=trusted,
                    order_ref=order_ref,
                    selected_method="orange_money",
                    binding=runtime_binding,
                    client=client,
                )
            session.rollback()
            assert len(client.requests) == 2

            print(f"P0D_PG17_WND_ORDER_UUID={order_ref}")
            print("P0D_PG17_WND_CANONICAL_TOTAL_XAF=3500")
            print(f"P0D_PG17_PAYMENT_REQUEST={first['payment_request_ref']}")
            print(f"P0D_PG17_PAYMENT_ATTEMPT={first['payment_attempt_ref']}")
            print(f"P0D_PG17_CHECKOUT_SESSION={first['checkout_session_id']}")
            print("P0D_PG17_PAYMENT_STATUS=PAYMENT_PENDING")
            print("P0D_PG17_COUNTS=request:1,intent:1,attempt:1,settlement:0")
            print("P0D_PG17_FALSE_PAID=NO")
    finally:
        engine.dispose()
