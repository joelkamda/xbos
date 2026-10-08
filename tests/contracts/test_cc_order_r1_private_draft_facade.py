from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from restaurant.customer_channel.contracts import H1BError, TrustedCheckoutScope
from restaurant.customer_channel.draft_order import (
    CustomerChannelDraftOrderAuthority,
    _client_command_ref,
)

ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_050_is_one_additive_successor_to_049_with_exact_three_tables():
    migration = source("alembic_neutral/versions/cc_order_draft_facade_050.py")
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert 'revision = "cc_order_draft_facade_050"' in migration
    assert 'down_revision = "cc_catalog_binding_price_code_case_049"' in migration
    assert up.count("CREATE TABLE public.") == 3
    for table in (
        "restaurant_customer_order_drafts",
        "restaurant_customer_order_draft_lines",
        "restaurant_customer_order_command_results",
    ):
        assert f"CREATE TABLE public.{table}" in up


def test_050_is_binding_only_and_does_not_repurpose_confirmation_or_price_truth():
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert "ALTER TABLE public.restaurant_customer_order_confirmations" not in up
    assert "UPDATE public.r1_restaurant_orders" not in up
    assert "UPDATE public.r1_restaurant_order_lines" not in up
    line_block = up[
        up.index("CREATE TABLE public.restaurant_customer_order_draft_lines"):
        up.index("CREATE INDEX ix_cc_order_draft_lines_projection")
    ]
    for forbidden in ("unit_price", "quantity", "line_total", "currency"):
        assert forbidden not in line_block


def test_one_draft_maps_to_one_r1_order_and_context_is_durable():
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert "CONSTRAINT uq_cc_order_draft_order UNIQUE(tenant_id,order_public_id)" in up
    for field in (
        "organization_unit_id",
        "location_id",
        "merchant_public_id",
        "context_binding_public_id",
        "catalog_binding_public_id",
        "catalog_binding_version",
        "order_public_id",
    ):
        assert field in up
    assert "source_channel_code<>'customer_channel'" in up


def test_create_and_command_reconciliation_routes_are_materialized():
    router = source("restaurant/customer_channel/router.py")
    for route in (
        '@router.post("/order-drafts")',
        '@router.get("/order-drafts/by-client-command-ref/{client_command_ref}")',
        '@router.get("/order-drafts/{draft_ref}")',
        '@router.post("/order-drafts/{draft_ref}/commands")',
        '@router.get("/order-commands/by-client-ref/{client_command_ref}")',
        '@router.post("/order-drafts/{draft_ref}/confirmation")',
        '@router.post("/order-drafts/{draft_ref}/submit")',
        '@router.get("/orders/{order_ref}")',
        '@router.post("/orders/{order_ref}/cancel")',
    ):
        assert route in router


def test_client_command_ref_is_trim_only_case_preserved_and_sha256():
    selected, digest = _client_command_ref(" AbC ")
    assert selected == "AbC"
    assert digest == hashlib.sha256(b"AbC").hexdigest()
    assert digest != _client_command_ref("abc")[1]
    with pytest.raises(H1BError):
        _client_command_ref("")
    with pytest.raises(H1BError):
        _client_command_ref("x" * 161)


def test_command_fingerprint_binds_context_merchant_location_and_expected_versions():
    scope = TrustedCheckoutScope(
        2, 1, 3, 4, UUID(int=10), UUID(int=11), UUID(int=12), "XAF", "trace"
    )
    one = CustomerChannelDraftOrderAuthority._command_fingerprint(
        operation="ADD_LINE",
        draft_ref=UUID(int=20),
        expected_versions={"draft": 1},
        body={"item_ref": "x"},
        scope=scope,
    )
    changed = CustomerChannelDraftOrderAuthority._command_fingerprint(
        operation="ADD_LINE",
        draft_ref=UUID(int=20),
        expected_versions={"draft": 2},
        body={"item_ref": "x"},
        scope=scope,
    )
    assert one != changed


def test_command_result_journal_is_tenant_unique_and_replay_conflicts_fail_closed():
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    repo = source("restaurant/customer_channel/repository.py")
    facade = source("restaurant/customer_channel/draft_order.py")
    assert "CONSTRAINT uq_cc_order_command_ref UNIQUE(tenant_id,client_command_ref_hash)" in up
    assert "pg_advisory_xact_lock" in repo
    assert "request_fingerprint" in repo
    assert "IDEMPOTENCY_CONFLICT" in facade
    assert "COMMAND_RESULT_UNKNOWN" in facade


def test_caller_cannot_select_tenant_merchant_location_or_price():
    router = source("restaurant/customer_channel/router.py")
    facade = source("restaurant/customer_channel/draft_order.py")
    create_block = router[
        router.index("async def create_order_draft"):
        router.index("async def reconcile_order_draft_create")
    ]
    assert '"client_command_ref", "service_mode"' in create_block
    for forbidden in ('"tenant"', '"merchant"', '"location"', '"price"', '"currency"'):
        assert forbidden not in create_block
    add_shape = facade[
        facade.index('"ADD_LINE": {'):
        facade.index('"REMOVE_LINE": {')
    ]
    for forbidden in ('"price"', '"price_ref"', '"currency"', '"merchant"', '"location"'):
        assert forbidden not in add_shape


def test_wrong_context_fails_closed_against_durable_draft_binding():
    facade = source("restaurant/customer_channel/draft_order.py")
    block = facade[facade.index("def _draft("):facade.index("def _fulfillment(")]
    assert 'row["organization_unit_id"]' in block
    assert 'row["location_id"]' in block
    assert 'row["merchant_public_id"]' in block
    assert 'row["context_binding_public_id"]' in block
    assert 'raise H1BError("CONTEXT_MISMATCH"' in block


def test_add_line_uses_server_catalog_binding_price_code_and_never_client_price():
    facade = source("restaurant/customer_channel/draft_order.py")
    adapters = source("restaurant/customer_channel/adapters.py")
    assert "price_code=binding.price_code" in facade
    assert "catalog_public_id=binding.catalog_public_id" in facade
    assert "price_scope_type=ScopeType(binding.scope_type)" in facade
    assert "price_code: str = PRICE_CODE" in adapters
    assert "ResolvePrice(" in adapters


def test_price_code_case_is_preserved_and_050_does_not_normalize_it():
    case_sql = source("alembic_neutral/sql/cc_catalog_binding_price_code_case_049_up.sql")
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert "price_code=btrim(price_code)" in case_sql
    assert "lower(" not in case_sql.lower()
    assert "lower(price_code)" not in up.lower()


def test_remove_and_quantity_mutations_reuse_r1_truth_and_versions():
    facade = source("restaurant/customer_channel/draft_order.py")
    assert "self.adapters.r1.remove_order_line(" in facade
    assert "RemoveOrderLine(" in facade
    assert "self.adapters.r1.change_line_quantity(" in facade
    assert "ChangeOrderLineQuantity(" in facade
    assert 'expected_versions["line"]' in facade


def test_nonzero_modifier_price_effect_fails_closed():
    adapters = source("restaurant/customer_channel/adapters.py")
    facade = source("restaurant/customer_channel/draft_order.py")
    assert 'Decimal(price.amount) != Decimal("0")' in adapters
    assert 'Decimal(item.price_amount_snapshot) != Decimal("0")' in facade
    assert 'raise H1BError("ORDER_NOT_READY"' in facade


def test_confirmation_table_remains_immutable_and_is_reused():
    old_sql = source("alembic_neutral/sql/cch_customer_channel_checkout_authority_up.sql")
    facade = source("restaurant/customer_channel/draft_order.py")
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert "restaurant_customer_confirmation_immutable" in old_sql
    assert "trg_cc_confirmation_immutable" in old_sql
    assert "self.repo.create_confirmation(" in facade
    assert "restaurant_customer_order_confirmations" not in up


def test_submit_uses_existing_backing_order_and_cc1_submit_journal():
    facade = source("restaurant/customer_channel/draft_order.py")
    block = facade[
        facade.index("def submit_draft("):
        facade.index("def reconcile_submit(")
    ]
    assert "self.adapters.open_order(" not in block
    assert 'f"cc1:{submit_hash}:submit"' in block
    assert "SubmitOrder(" in block
    assert "bind_confirmation_order" in block
    assert 'to_state="submitted"' in block


def test_unknown_submit_reconciliation_preserves_existing_path():
    facade = source("restaurant/customer_channel/draft_order.py")
    service = source("restaurant/customer_channel/service.py")
    repo = source("restaurant/customer_channel/repository.py")
    assert "self.checkout.reconcile_order(" in facade
    assert 'f"cc1:{submit_hash}:submit"' in service
    assert "command_type='submit_order'" in repo


def test_fulfillment_successor_changes_existing_r1_columns_without_new_r1_column():
    contracts = source("restaurant/r1/contracts.py")
    service = source("restaurant/r1/service.py")
    repo = source("restaurant/r1/sql_repository.py")
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    assert "class ChangeOrderFulfillment" in contracts
    assert "def change_order_fulfillment" in service
    assert "SET service_mode_id=:mode,service_session_id=:session,party_id=:party" in repo
    assert "ALTER TABLE public.r1_restaurant_orders" not in up


def test_order_projection_does_not_invent_preparing_ready_or_accepted():
    facade = source("restaurant/customer_channel/draft_order.py")
    block = facade[facade.index('state = {'):facade.index('return {', facade.index('state = {'))]
    assert '"open": "DRAFT"' in block
    assert '"submitted": "SUBMITTED"' in block
    assert '"cancelled": "CANCELLED"' in block
    for forbidden in ("PREPARING", "READY", "ACCEPTED"):
        assert forbidden not in block


def test_submitted_cancel_fails_closed_and_never_becomes_refund():
    facade = source("restaurant/customer_channel/draft_order.py")
    block = facade[facade.index("def cancel_order("):]
    assert "order.status is not OrderStatus.OPEN" in block
    assert "Submitted cancellation intentionally fails closed" in block
    assert "refund" in block.lower()
    assert "create_payment_request" not in block


def test_availability_is_commercial_only_and_no_so3_stock_claim():
    facade = source("restaurant/customer_channel/draft_order.py")
    assert '"orderable"' in facade
    assert '"not_orderable"' in facade
    assert "commercial_orderability" in facade
    assert "so3" not in facade.lower()
    assert "stock_on_hand" not in facade.lower()


def test_draft_backed_submit_reconciliation_rechecks_durable_scope():
    facade = source("restaurant/customer_channel/draft_order.py")
    router = source("restaurant/customer_channel/router.py")
    block = facade[
        facade.index("def reconcile_submit("):
        facade.index("def read_order(", facade.index("def reconcile_submit("))
    ]
    assert "self.checkout.reconcile_order(" in block
    assert "self.repo.draft_by_order(" in block
    assert "self._draft(scope" in block
    route = router[
        router.index('async def reconcile_order('):
        router.index('@router.post("/orders/{order_ref}/payment-request")')
    ]
    assert "CustomerChannelDraftOrderAuthority(db)" in route
    assert "authority.reconcile_submit(" in route


def test_facade_has_no_payment_gateway_provider_side_effect():
    facade = source("restaurant/customer_channel/draft_order.py").lower()
    for forbidden in (
        "create_payment_request",
        "xafpaygateway",
        "provider_call",
        "create_payment(",
        "create_intent(",
        "create_attempt(",
    ):
        assert forbidden not in facade


def test_draft_line_table_is_item_binding_only_and_command_result_can_return_line_ref():
    up = source("alembic_neutral/sql/cc_order_draft_facade_050_up.sql")
    line_block = up[
        up.index("CREATE TABLE public.restaurant_customer_order_draft_lines"):
        up.index("CREATE INDEX ix_cc_order_draft_lines_projection")
    ]
    assert "order_line_public_id UUID NOT NULL" in line_block
    assert "item_public_id UUID NOT NULL" in line_block
    command_block = up[
        up.index("CREATE TABLE public.restaurant_customer_order_command_results"):
        up.index("CREATE INDEX ix_cc_order_command_draft")
    ]
    assert "line_public_id UUID NULL" in command_block
    assert "order_public_id UUID NULL" in command_block
