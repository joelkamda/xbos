"""Disposable PostgreSQL 17 durability of nonsecret one-time custody nonce."""
from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from test_swes_r2_wnd_bootstrap_disposable_pg17 import disposable_url  # noqa: F401

from restaurant.customer_channel.swes_r48_gateway_custody import _CUSTODY_NONCE_SQL
from scripts import swes_r2_wnd_synthetic_fixture_bootstrap as fixture


@pytest.fixture(scope="module")
def prepared_pg17(request):
    # The imported fixture provides a disposable, isolated PG17 instance.
    url = request.getfixturevalue("disposable_url")
    fixture.execute(url, "apply", hosted=False)
    return url


def test_gateway_custody_nonce_durable_single_use_pg17(prepared_pg17):
    key = "r48:gateway:checkout:" + str(uuid4())
    credential_id = uuid4()
    fingerprint = sha256(b"synthetic-signed-envelope-not-a-secret").hexdigest()
    engine = create_engine(prepared_pg17)
    try:
        args = {"key": key, "fingerprint": fingerprint, "id": str(credential_id)}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one()
            assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "off"
            assert conn.execute(_CUSTODY_NONCE_SQL, args).scalar_one() > 0
        # Separate transaction and connection prove duplicate nonce denied.
        with engine.begin() as conn:
            assert conn.execute(_CUSTODY_NONCE_SQL, args).scalar() is None
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT command_type, result_type, result_public_id,
                       request_fingerprint
                FROM public.r1_restaurant_commands
                WHERE tenant_id=910001 AND command_key=:key
            """), {"key": key}).mappings().one()
            assert row["command_type"] == "gateway_checkout_custody"
            assert row["result_type"] == "restricted_gateway_credential"
            assert str(row["result_public_id"]) == str(credential_id)
            assert row["request_fingerprint"] == fingerprint
            assert conn.execute(text("""
                SELECT count(*) FROM public.r1_restaurant_commands
                WHERE tenant_id=910001 AND command_key=:key
            """), {"key": key}).scalar_one() == 1
    finally:
        engine.dispose()


def test_failure_before_runtime_publish_rolls_back_real_pg17_nonce(prepared_pg17):
    key = "r48:gateway:checkout:" + str(uuid4())
    args = {
        "key": key,
        "fingerprint": sha256(b"synthetic-failed-install").hexdigest(),
        "id": str(uuid4()),
    }
    engine = create_engine(prepared_pg17)
    try:
        # Simulate a failed runtime installation after inserting the nonce.
        # There must be NO commit.
        with engine.connect() as conn:
            txn = conn.begin()
            assert conn.execute(_CUSTODY_NONCE_SQL, args).scalar_one() > 0
            txn.rollback()
        with engine.connect() as conn:
            assert conn.execute(text("""
                SELECT count(*) FROM public.r1_restaurant_commands
                WHERE tenant_id=910001 AND command_key=:key
            """), {"key": key}).scalar_one() == 0
        # An authorized retry can persist the SAME nonce once.
        with engine.begin() as conn:
            assert conn.execute(_CUSTODY_NONCE_SQL, args).scalar_one() > 0
        with engine.begin() as conn:
            assert conn.execute(_CUSTODY_NONCE_SQL, args).scalar() is None
    finally:
        engine.dispose()
