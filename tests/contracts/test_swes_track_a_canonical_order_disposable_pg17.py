"""Actual disposable PostgreSQL 17 canonical Track A order persistence.

Uses migrated isolated loopback PG17 and R2/R3/R4 synthetic fixtures.
The synthetic IA0 receipt is deliberately TEST data, not a real Twilio
attestation. This qualifies DB commerce, not hosted/bilateral authorization.
No Render access or payment action; transaction rollback on any failure.
"""
# ruff: noqa: F811 - pytest's imported fixture is injected by argument name
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from test_swes_r2_wnd_bootstrap_disposable_pg17 import disposable_url  # noqa: F401

from restaurant.customer_channel import swes_track_a_canonical_order as order
from restaurant.customer_channel.contracts import H1BError, TrustedCheckoutScope
from restaurant.customer_channel.swes_r48_ia0_writer import (
    VerifiedCCEvent,
    persist_verified_event,
)
from scripts import swes_r2_wnd_synthetic_fixture_bootstrap as fixture
from scripts import swes_r3_wnd_test_menu_publish as menu
from scripts import swes_r4_wnd_phase1_bundle as phase1


@pytest.fixture(scope="module")
def prepared_db(disposable_url):
    # Disposable-only sequence reservation reproduces the hosted synthetic
    # location ID 5 without modifying any real tenant or production tables.
    engine = create_engine(disposable_url)
    try:
        with engine.begin() as conn:
            assert conn.execute(text(
                "SELECT setval(pg_get_serial_sequence('public.locations', 'id'),4,true)"
            )).scalar_one() == 4
    finally:
        engine.dispose()
    assert fixture.execute(disposable_url, "dry-run", hosted=False)["before"]["tenants"] == 0
    fixture.execute(disposable_url, "apply", hosted=False)
    menu.publish(disposable_url, apply=True, hosted=False)
    phase1.execute(disposable_url, apply=True, hosted=False)
    return disposable_url


def _event():
    now = datetime.now(timezone.utc)
    return VerifiedCCEvent(
        tenant_id=910001, location_id=5, event_id="e" * 64,
        fingerprint="f" * 64, sender_hmac="a" * 64,
        receipt_reference="b" * 64,
        correlation_ref=uuid4(),
        received_at=now - timedelta(seconds=2),
        expires_at=now + timedelta(minutes=4),
    )


def _scope(conn, event, session):
    b = conn.execute(text("""
        SELECT b.public_id FROM public.ia0_interaction_context_bindings b
        WHERE b.tenant_id=910001 AND b.source_reference=:event
          AND b.correlation_id=:corr
    """), {"event": event.event_id, "corr": str(event.correlation_ref)}).scalar_one()
    mapping = conn.execute(text("""
        SELECT branch_id, organization_unit_id FROM
        public.legacy_branch_structural_mappings
        WHERE tenant_id=910001 AND location_id=5
    """)).mappings().one()
    return TrustedCheckoutScope(
        tenant_id=910001,
        branch_id=int(mapping["branch_id"]),
        organization_unit_id=int(mapping["organization_unit_id"]),
        location_id=5,
        merchant_public_id=order.MERCHANT,
        context_binding_public_id=UUID(str(b)),
        service_identity_public_id=uuid4(),
        currency="XAF",
        correlation_ref=str(event.correlation_ref),
    )


def test_actual_canonical_takeaway_order_is_submitted_server_priced_and_replay_safe(prepared_db):
    eng = create_engine(prepared_db)
    try:
        with eng.connect() as conn:
            tx = conn.begin()
            try:
                event = _event()
                session = persist_verified_event(
                    conn, event,
                    authorize_service=lambda _: True,
                    verify_cc_receipt=lambda _: True,
                )
                scope = _scope(conn, event, session)
                first = order._order_from_verified_context(
                    conn, scope=scope, event_id=event.event_id,
                    correlation=event.correlation_ref,
                )
                assert isinstance(first, UUID)
                actual = conn.execute(text("""
                    SELECT o.public_id,o.lifecycle_status, r.mode_code,
                           count(l.id) line_count,
                           sum(l.quantity*l.unit_price_snapshot) AS amount
                    FROM public.r1_restaurant_orders o
                    JOIN public.r1_restaurant_service_modes r ON
                      r.tenant_id=o.tenant_id AND r.id=o.service_mode_id
                    JOIN public.r1_restaurant_order_lines l ON
                      l.tenant_id=o.tenant_id AND l.order_id=o.id
                    WHERE o.tenant_id=910001 AND o.public_id=:id
                    GROUP BY o.public_id,o.lifecycle_status,r.mode_code
                """), {"id": str(first)}).mappings().one()
                assert (actual["public_id"], actual["lifecycle_status"]) == (
                    first, "submitted"
                )
                assert actual["mode_code"] == "takeaway"
                assert actual["line_count"] == 1
                assert Decimal(actual["amount"]) == Decimal(1000)
                assert conn.execute(text("""
                    SELECT administration_state FROM public.pa_merchants
                    WHERE tenant_id=910001 AND public_id=:id
                """), {"id": str(order.MERCHANT)}).scalar_one() == "registered"
                second = order._order_from_verified_context(
                    conn, scope=scope, event_id=event.event_id,
                    correlation=event.correlation_ref,
                )
                assert second == first
                assert conn.execute(text("""
                    SELECT count(*) FROM public.r1_restaurant_orders
                    WHERE tenant_id=910001
                """)).scalar_one() == 1
                tx.commit()
            except BaseException:
                tx.rollback()
                raise
        # Read from an independently acquired connection after COMMIT.
        with eng.connect() as readback:
            assert readback.execute(text("""
                SELECT count(*) FROM public.r1_restaurant_orders
                WHERE tenant_id=910001 AND lifecycle_status='submitted'
            """)).scalar_one() == 1
    finally:
        eng.dispose()


def test_wrong_event_cannot_create_second_order(prepared_db):
    eng = create_engine(prepared_db)
    try:
        with eng.connect() as conn:
            tx = conn.begin()
            try:
                # No synthetic receipt for this wrong event; reject before effects.
                with pytest.raises(H1BError, match="CONTEXT_MISMATCH"):
                    order._read_source(
                        conn, binding=uuid4(), correlation=uuid4(),
                        event_id="f" * 64,
                    )
            finally:
                tx.rollback()
        with eng.connect() as conn:
            assert conn.execute(text("""
                SELECT count(*) FROM public.r1_restaurant_orders WHERE tenant_id=910001
            """)).scalar_one() == 1
    finally:
        eng.dispose()
