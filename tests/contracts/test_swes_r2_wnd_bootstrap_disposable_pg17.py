"""Source-faithful SWES TEST fixture rehearsal on disposable loopback PG17 ONLY.

Creates a temporary local PGDATA and database, replays neutral migrations,
proves atomic rollback on injected SQL failure, verifies exact successful
fixture and duplicate refusal, and shuts down the temporary cluster.
Never connects to Render and never calls providers.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, text

from alembic import command
from scripts import swes_r2_wnd_synthetic_fixture_bootstrap as target

ROOT = Path(__file__).resolve().parents[2]
PG = Path("C:/Program Files/PostgreSQL/17/bin")
DB = "swes_r2_wnd_bootstrap_disposable"
USER = "swes_r2_local"


def _run(args: list[str], env: dict[str, str], timeout=180) -> None:
    # pg_ctl spawns a server that may inherit output handles on Windows.
    # DEVNULL avoids holding subprocess.run's capture pipes open indefinitely.
    if Path(args[0]).stem.lower() == "pg_ctl":
        proc = subprocess.run(args, env=env, check=False, timeout=timeout,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stderr = ""
    else:
        proc = subprocess.run(args, env=env, check=False, timeout=timeout,
                              capture_output=True, text=True)
        stderr = proc.stderr
    if proc.returncode:
        raise RuntimeError("SWES_LOCAL_SUBPROCESS_FAILED: "
                           + Path(args[0]).name + " " + stderr[-800:])


@pytest.fixture(scope="module")
def disposable_url():
    for binary in ("initdb.exe", "pg_ctl.exe", "psql.exe"):
        if not (PG / binary).is_file():
            pytest.skip("local PG17 binary unavailable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        key: val for key, val in os.environ.items()
        if not key.upper().startswith("PG")
        and key.upper() not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    with tempfile.TemporaryDirectory(prefix="swes_r2_disposable_pg17_") as temp:
        pgdata = str(Path(temp) / "pgdata")
        log = str(Path(temp) / "postgres.log")
        started = False
        try:
            _run([str(PG / "initdb.exe"), "-D", pgdata, "-A", "trust",
                  "-U", USER, "--no-instructions", "--no-sync"], env)
            _run([str(PG / "pg_ctl.exe"), "-D", pgdata, "-l", log, "-o",
                  f"-h 127.0.0.1 -p {port} -c max_connections=20",
                  "-w", "start"], env)
            started = True
            _run([str(PG / "psql.exe"), "-X", "-h", "127.0.0.1",
                  "-p", str(port), "-U", USER, "-d", "postgres",
                  "-v", "ON_ERROR_STOP=1",
                  "-c", f'CREATE DATABASE "{DB}"'], env)
            url = f"postgresql+psycopg://{USER}@127.0.0.1:{port}/{DB}"
            config = Config(str(ROOT / "alembic_neutral.ini"))
            previous = {name: os.environ.get(name)
                        for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL",
                                     "ALEMBIC_NEUTRAL_VERSION_TABLE")}
            try:
                os.environ["DATABASE_URL"] = url
                os.environ["MIGRATION_DATABASE_URL"] = url
                os.environ["ALEMBIC_NEUTRAL_VERSION_TABLE"] = "alembic_version"
                command.upgrade(config, "head")
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            engine = create_engine(url)
            try:
                with engine.connect() as conn:
                    head = conn.execute(text(
                        "SELECT version_num FROM public.alembic_version"
                    )).scalar_one()
                assert head == "cc_order_draft_facade_050"
            finally:
                engine.dispose()
            yield url
        finally:
            if started:
                _run([str(PG / "pg_ctl.exe"), "-D", pgdata,
                      "-m", "immediate", "-w", "stop"], env)


def test_source_faithful_pg17_atomic_bootstrap(disposable_url, monkeypatch):
    original = target.create_engine
    before = target.execute(disposable_url, "dry-run", hosted=False)
    assert all(count == 0 for count in before["before"].values())

    instrumented = original(disposable_url)
    def inject_failure(_conn, _cursor, statement, _params, _context, _many):
        if "INSERT INTO public.so1_prices" in statement:
            raise RuntimeError("SWES_DISPOSABLE_ROLLBACK_INJECTION")
    event.listen(instrumented, "before_cursor_execute", inject_failure)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(target, "create_engine", lambda *_a, **_k: instrumented)
            with pytest.raises(RuntimeError, match="ROLLBACK_INJECTION"):
                target.execute(disposable_url, "apply", hosted=False)
    finally:
        event.remove(instrumented, "before_cursor_execute", inject_failure)
        instrumented.dispose()

    after_fault = target.execute(disposable_url, "dry-run", hosted=False)
    assert after_fault["before"] == before["before"]

    applied = target.execute(disposable_url, "apply", hosted=False)
    assert applied["after"]["tenants"] == 1
    assert applied["after"]["pa_merchants"] == 1
    assert applied["after"]["so1_prices"] == 1
    assert applied["after"]["restaurant_customer_catalog_read_bindings"] == 1
    assert applied["after"]["service_identities"] == 0
    assert applied["after"]["r1_restaurant_orders"] == 0
    assert applied["price"] == {"currency": "XAF", "amount": 1000}
    assert applied["merchant_state"] == "registered"
    with pytest.raises(RuntimeError, match="CANDIDATE_TENANT_NOT_EMPTY"):
        target.execute(disposable_url, "apply", hosted=False)

    eng = original(disposable_url)
    try:
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT m.administration_state, p.currency, p.amount "
                "FROM public.pa_merchants m "
                "JOIN public.restaurant_customer_catalog_read_bindings b "
                "ON b.merchant_public_id=m.public_id "
                "JOIN public.so1_catalogs c ON c.public_id=b.catalog_public_id "
                "JOIN public.so1_catalog_entries e ON e.catalog_id=c.id "
                "JOIN public.so1_prices p ON p.tenant_id=e.tenant_id "
                "AND p.atomic_unit_id=e.atomic_unit_id "
                "AND p.price_code=b.price_code "
                "WHERE m.tenant_id=:tenant"
            ), {"tenant": target.TENANT}).one()
            assert row.administration_state == "registered"
            assert row.currency == "XAF"
            assert row.amount == 1000
    finally:
        eng.dispose()

def test_swes_r3_menu_disposable_pg17_atomic_and_duplicate(disposable_url, monkeypatch):
    from scripts import swes_r3_wnd_test_menu_publish as menu

    initial = target.execute(disposable_url, "dry-run", hosted=False)
    if all(n == 0 for n in initial["before"].values()):
        target.execute(disposable_url, "apply", hosted=False)
    else:
        assert initial["before"]["tenants"] == 1
        assert initial["before"]["so1_catalog_entries"] == 1

    before = menu.publish(disposable_url, apply=False, hosted=False)
    assert before["before"] == {
        "r2_restaurant_menu_sections": 0,
        "r2_restaurant_menu_section_entries": 0,
    }
    original = menu.create_engine
    instrumented = original(disposable_url)

    def injected_failure(_conn, _cur, sql, _params, _ctx, _many):
        if "INSERT INTO public.r2_restaurant_menu_section_entries" in sql:
            raise RuntimeError("SWES_R3_DISPOSABLE_TEST_ROLLBACK")

    event.listen(instrumented, "before_cursor_execute", injected_failure)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(menu, "create_engine", lambda *_a, **_kw: instrumented)
            with pytest.raises(RuntimeError, match="TEST_ROLLBACK"):
                menu.publish(disposable_url, apply=True, hosted=False)
    finally:
        event.remove(instrumented, "before_cursor_execute", injected_failure)
        instrumented.dispose()

    assert menu.publish(disposable_url, apply=False, hosted=False)["before"] == before["before"]
    created = menu.publish(disposable_url, apply=True, hosted=False)
    assert created["after"] == {
        "r2_restaurant_menu_sections": 1,
        "r2_restaurant_menu_section_entries": 1,
    }
    with pytest.raises(RuntimeError, match="MENU_ALREADY_PRESENT"):
        menu.publish(disposable_url, apply=True, hosted=False)

    engine = original(disposable_url)
    try:
        with engine.connect() as c:
            menu_current = c.execute(text("""
                SELECT count(*)
                FROM public.r2_restaurant_menu_sections s
                JOIN public.r2_restaurant_menu_section_entries x
                  ON x.tenant_id=s.tenant_id AND x.section_id=s.id
                JOIN public.so1_catalogs cat
                  ON cat.tenant_id=s.tenant_id AND cat.id=s.catalog_id
                WHERE s.tenant_id=:t AND cat.public_id=CAST(:catalog AS uuid)
                  AND x.catalog_entry_public_id=CAST(:entry AS uuid)
                  AND s.active AND s.effective_from<=now()
                  AND x.effective_from<=now()
            """), {
                "t": target.TENANT, "catalog": menu.CATALOG,
                "entry": menu.ENTRY,
            }).scalar_one()
            assert menu_current == 1
    finally:
        engine.dispose()

def test_swes_wnd01_inventory_category_policy_for_seeded_item(disposable_url, monkeypatch):
    """Establish actual resolver semantics for SWES-16, not a mock category."""
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    from types import SimpleNamespace

    import core.domain.inventory.taxonomy_profile as taxonomy
    from core.domain.inventory.service import InventoryService

    prestate = target.execute(disposable_url, "dry-run", hosted=False)
    if prestate["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)
    else:
        assert prestate["before"]["tenants"] == 1

    engine = create_engine(disposable_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, name, sku, unit_type, is_active, meta
                FROM public.atomic_units
                WHERE tenant_id=:tenant AND public_id=CAST(:uid AS uuid)
            """), {
                "tenant": target.TENANT,
                "uid": str(target.IDS["unit"]),
            }).mappings().one()
            unit_id = row["id"]
            assert row["sku"] == target.SKU
            assert row["unit_type"] == "product"
            assert row["is_active"] is True
            assert row["meta"] == {
                "test_only": True, "campaign": "PCR_V17_SWES_R2",
            }
            taxonomy_count = conn.execute(text("""
                SELECT count(*) FROM public.atomic_unit_taxonomy
                WHERE atomic_unit_id=:unit
            """), {"unit": unit_id}).scalar_one()
            assert taxonomy_count == 0
            item_count = conn.execute(text("""
                SELECT count(*) FROM public.inventory_items
                WHERE tenant_id=:tenant AND atomic_unit_id=:unit
            """), {"tenant": target.TENANT, "unit": unit_id}).scalar_one()
            assert item_count == 0
        # Use the true PG17 fixture row, while binding ORM loader edges
        # explicitly. An unrelated Payment model registry is not initialized
        # in this isolated test and must not be represented as a policy failure.
        unit = SimpleNamespace(
            id=unit_id, name=row["name"], meta=row["meta"],
        )
        monkeypatch.setattr(taxonomy, "_load_atomic_unit", lambda *_a, **_k: unit)
        monkeypatch.setattr(taxonomy, "_load_commerce_nodes", lambda *_a, **_k: {})
        monkeypatch.setattr(
            taxonomy, "_load_unit_commerce_mapping_nodes", lambda *_a, **_k: [],
        )
        profile = taxonomy.resolve_inventory_profile(
            None, tenant_id=target.TENANT, atomic_unit_id=unit_id,
        )
        assert profile["stock_tracked"] is False
        assert profile["inventory_family"] == "non_inventory"
        assert profile["cost_mode"] == "none"
        assert profile["allow_negative_stock"] is False
        assert profile["disable_when_out"] is False
        assert profile["source"] == "taxonomy_non_inventory"
        status = InventoryService.stock_status_for_quantity(
            quantity_on_hand=0, is_active=True,
        )
        assert status["stock_status"] == "out_of_stock"
        assert status["is_sellable"] is False
        # The real inventory-service sale gate is disable_when_out;
        # the zero-quantity generic TEST item is NOT disabled by that gate.
        assert not (profile["disable_when_out"] and
                    status["stock_status"] == "out_of_stock")
    finally:
        engine.dispose()

@pytest.mark.parametrize(
    ("policy_meta", "expected_family", "expected_stock", "expected_disable",
     "expected_negative"),
    [
        ({"inventory_family": "bar", "track_stock": True},
         "bar", True, True, False),
        ({"inventory_family": "kitchen", "track_stock": True},
         "kitchen", True, False, True),
        ({"inventory_family": "other", "track_stock": True},
         "other", True, True, False),
        ({"inventory_family": "non_inventory", "track_stock": False},
         "non_inventory", False, False, False),
    ],
)
def test_swes_wnd01_explicit_category_stock_policy_matrix(
    disposable_url, monkeypatch, policy_meta, expected_family,
    expected_stock, expected_disable, expected_negative,
):
    """Exercise genuine taxonomy policy alternatives without live mutation."""
    from types import SimpleNamespace

    monkeypatch.setenv("DATABASE_URL", disposable_url)
    import core.domain.inventory.taxonomy_profile as taxonomy

    mock_unit = SimpleNamespace(
        id=1001, name="SWES Synthetic Menu Item", meta=policy_meta,
    )
    monkeypatch.setattr(
        taxonomy, "_load_atomic_unit", lambda *_a, **_kw: mock_unit,
    )
    monkeypatch.setattr(
        taxonomy, "_load_commerce_nodes", lambda *_a, **_kw: {},
    )
    monkeypatch.setattr(
        taxonomy, "_load_unit_commerce_mapping_nodes", lambda *_a, **_kw: [],
    )
    profile = taxonomy.resolve_inventory_profile(
        None, tenant_id=target.TENANT, atomic_unit_id=mock_unit.id,
    )
    assert profile["inventory_family"] == expected_family
    assert profile["stock_tracked"] is expected_stock
    assert profile["disable_when_out"] is expected_disable
    assert profile["allow_negative_stock"] is expected_negative
    assert profile["source"] == "meta"

def test_swes_wnd02_explicit_kitchen_policy_pg17_cas_and_replay(
    disposable_url, monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    from types import SimpleNamespace

    import core.domain.inventory.taxonomy_profile as taxonomy
    from scripts import swes_r4_wnd_synthetic_food_policy as policy
    prior = target.execute(disposable_url, "dry-run", hosted=False)
    if prior["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)

    before = policy.qualify(disposable_url, apply=False, hosted=False)
    assert before["original_meta"] == policy.PREVIOUS
    assert before["initial_taxonomy_assignments"] == 0
    assert before["initial_stock_positions"] == 0

    original = policy.create_engine
    injected = original(disposable_url)

    def fail_before_update(_c, _cur, sql, _p, _ctx, _many):
        if "UPDATE public.atomic_units" in sql:
            raise RuntimeError("SWES_TEST_INJECTED_UPDATE_FAILURE")

    event.listen(injected, "before_cursor_execute", fail_before_update)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(policy, "create_engine", lambda *_a, **_kw: injected)
            with pytest.raises(RuntimeError, match="INJECTED_UPDATE_FAILURE"):
                policy.qualify(disposable_url, apply=True, hosted=False)
    finally:
        event.remove(injected, "before_cursor_execute", fail_before_update)
        injected.dispose()

    unchanged = policy.qualify(disposable_url, apply=False, hosted=False)
    assert unchanged["original_meta"] == policy.PREVIOUS
    assert unchanged["before_row_version"] == before["before_row_version"]

    result = policy.qualify(disposable_url, apply=True, hosted=False)
    assert result["classification_applied"] is True
    assert result["after_row_version"] == before["before_row_version"] + 1

    with pytest.raises(RuntimeError, match="PREVIOUS_METADATA_MISMATCH"):
        policy.qualify(disposable_url, apply=True, hosted=False)

    engine = original(disposable_url)
    try:
        with engine.connect() as conn:
            unit = conn.execute(text("""
                SELECT id, name, meta, row_version FROM public.atomic_units
                WHERE tenant_id=:t AND sku=:sku
            """), {"t": target.TENANT, "sku": target.SKU}).mappings().one()
            assert unit["meta"] == policy.EXPECTED
            assert unit["row_version"] == result["after_row_version"]
            synthetic = SimpleNamespace(
                id=unit["id"], name=unit["name"], meta=unit["meta"],
            )
        with monkeypatch.context() as patch:
            patch.setattr(taxonomy, "_load_atomic_unit", lambda *_a, **_k: synthetic)
            patch.setattr(taxonomy, "_load_commerce_nodes", lambda *_a, **_k: {})
            patch.setattr(taxonomy, "_load_unit_commerce_mapping_nodes",
                          lambda *_a, **_k: [])
            profile = taxonomy.resolve_inventory_profile(
                None, tenant_id=target.TENANT, atomic_unit_id=synthetic.id,
            )
        assert profile["inventory_family"] == "kitchen"
        assert profile["stock_tracked"] is True
        assert profile["cost_mode"] == "expense_allocated"
        assert profile["allow_negative_stock"] is True
        assert profile["disable_when_out"] is False
        assert profile["source"] == "meta"
    finally:
        engine.dispose()

def test_swes_wnd03_pg17_authoritative_price_scope_and_negative_cases(
    disposable_url,
):
    """Prove SO1 price lookup rejects bad code/currency/time and returns XAF."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from shared_operations.so1.contracts import ResolvePrice, ScopeType, TargetType
    from shared_operations.so1.sql_repository import SQLSO1Repository

    prestate = target.execute(disposable_url, "dry-run", hosted=False)
    if prestate["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)
    engine = create_engine(disposable_url)
    try:
        with Session(engine) as session:
            repo = SQLSO1Repository(session)
            now = datetime.now(timezone.utc)
            def resolve(code, currency, when, scope=ScopeType.TENANT, scope_id=None,
                        tenant=target.TENANT):
                return repo.resolve_price(ResolvePrice(
                    tenant, TargetType.ATOMIC_UNIT, target.IDS["unit"],
                    code, currency, when, scope, scope_id,
                ))
            price = resolve(target.PRICE_CODE, "XAF", now)
            assert price is not None
            assert price.public_id == target.IDS["price"]
            assert price.amount == Decimal(1000)
            assert price.currency == "XAF"
            assert price.price_code == "swes-retail"
            assert price.scope_type is ScopeType.TENANT
            assert price.scope_id is None
            assert price.row_version == 1
            # A location query falls back to the tenant-wide price.
            fallback = resolve(
                target.PRICE_CODE, "XAF", now, ScopeType.LOCATION, 999999,
            )
            assert fallback is not None
            assert fallback.public_id == price.public_id
            assert resolve("retail", "XAF", now) is None
            assert resolve("SWES-RETAIL", "XAF", now) is None
            assert resolve(target.PRICE_CODE, "USD", now) is None
            assert resolve(
                target.PRICE_CODE, "XAF", now - timedelta(days=365),
            ) is None
            assert resolve(
                target.PRICE_CODE, "XAF", now, tenant=target.TENANT+1,
            ) is None
            binding = session.execute(text("""
                SELECT price_code,currency,scope_type,scope_id,row_version
                FROM public.restaurant_customer_catalog_read_bindings
                WHERE tenant_id=:t
            """), {"t": target.TENANT}).mappings().one()
            assert binding["price_code"] == price.price_code
            assert binding["currency"] == "XAF"
            assert binding["scope_type"] == "tenant"
            assert binding["scope_id"] is None
            assert binding["row_version"] == 1
    finally:
        engine.dispose()


def test_swes_wnd04_remote_takeaway_contract_in_source():
    """Prove intended minimal remote order mode requires a contact binding."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    src = (root / "restaurant" / "customer_channel" / "draft_order.py").read_text(
        encoding="utf8",
    )
    r1 = (root / "restaurant" / "r1" / "service.py").read_text(
        encoding="utf8",
    )
    assert 'mode_code not in {"dine_in", "takeaway", "delivery"}' in src
    assert 'elif mode_code == "takeaway":' in src
    assert "contact_ref is None" in src
    assert 'mode_code == "dine_in":' in src
    assert "allows_remote_origin" in r1
    assert "mode.requires_session" in r1

def test_swes_wnd_phase1_bundle_disposable_pg17_atomic_rollbacks(disposable_url, monkeypatch):
    """WND02/03/04 all-or-nothing TEST food, location pricing, takeaway."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from scripts import swes_r3_wnd_test_menu_publish as menu
    from scripts import swes_r4_wnd_phase1_bundle as bundle
    from shared_operations.so1.contracts import ResolvePrice, ScopeType, TargetType
    from shared_operations.so1.sql_repository import SQLSO1Repository

    initial = target.execute(disposable_url, "dry-run", hosted=False)
    if initial["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)
    menu_current = menu.publish(disposable_url, apply=False, hosted=False)
    if menu_current["before"]["r2_restaurant_menu_sections"] == 0:
        menu.publish(disposable_url, apply=True, hosted=False)

    engine = create_engine(disposable_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(text("""
                SELECT id,meta FROM public.atomic_units
                WHERE tenant_id=:t AND sku=:sku
            """), {"t": target.TENANT, "sku": target.SKU}).mappings().one()
            if row["meta"] == bundle.FOOD_META:
                # Test-only reset of state left by an earlier successful local
                # classification test; never used against any hosted service.
                conn.execute(text("""
                    UPDATE public.atomic_units SET meta=CAST(:original AS jsonb),
                    row_version=row_version+1 WHERE id=:id AND tenant_id=:t
                """), {
                    "original": json.dumps(bundle.PREVIOUS,sort_keys=True),
                    "id": row["id"], "t": target.TENANT,
                })
        before = bundle.execute(disposable_url, apply=False, hosted=False)
        assert before["before"]["binding_scope"] == "tenant"
        assert before["before"]["takeaway_modes"] == 0
        original = bundle.create_engine
        injected = original(disposable_url)

        def fail_on_mode(_conn, _cursor, sql, _params, _ctx, _many):
            if "INSERT INTO public.r1_restaurant_service_modes" in sql:
                raise RuntimeError("SWES_INJECTED_MODE_FAILURE")
        event.listen(injected, "before_cursor_execute", fail_on_mode)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(bundle, "create_engine", lambda *_a, **_kw: injected)
                with pytest.raises(RuntimeError, match="INJECTED_MODE_FAILURE"):
                    bundle.execute(disposable_url, apply=True, hosted=False)
        finally:
            event.remove(injected, "before_cursor_execute", fail_on_mode)
            injected.dispose()
        assert bundle.execute(disposable_url, apply=False, hosted=False)["before"] == before["before"]
        applied = bundle.execute(disposable_url, apply=True, hosted=False)
        assert applied["applied"] is True
        assert applied["after"]["binding_scope"] == "location"
        assert applied["after"]["binding_row_version"] == (
            before["before"]["binding_row_version"]+1
        )
        with pytest.raises(RuntimeError, match="PRESTATE_MISMATCH"):
            bundle.execute(disposable_url, apply=True, hosted=False)

        with Session(engine) as session:
            resolved = SQLSO1Repository(session).resolve_price(ResolvePrice(
                target.TENANT, TargetType.ATOMIC_UNIT, target.IDS["unit"],
                "swes-retail", "XAF", datetime.now(timezone.utc),
                ScopeType.LOCATION, applied["after"]["binding_scope_id"],
            ))
            assert resolved is not None
            assert resolved.amount == Decimal(1000)
            assert resolved.scope_type is ScopeType.TENANT
            row = session.execute(text("""
                SELECT m.mode_code,m.active,m.requires_session,
                       m.allows_remote_origin, b.scope_type,b.scope_id,
                       b.location_id
                FROM public.r1_restaurant_service_modes m
                JOIN public.restaurant_customer_catalog_read_bindings b
                  ON b.tenant_id=m.tenant_id
                WHERE m.tenant_id=:t AND m.mode_code='takeaway'
            """), {"t":target.TENANT}).mappings().one()
            assert row["mode_code"] == "takeaway"
            assert row["active"] is True
            assert row["requires_session"] is False
            assert row["allows_remote_origin"] is True
            assert row["scope_type"] == "location"
            assert row["scope_id"] == row["location_id"]
    finally:
        engine.dispose()

def test_swes_wnd05_pg17_canonical_takeaway_order_contract_rehearsal(disposable_url):
    """Prove real R1 SQL order/line/idempotency locally; hosted auth remains held."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from restaurant.r1.contracts import AddLine, OpenOrder, OrderStatus
    from restaurant.r1.contracts import TargetType as R1TargetType
    from restaurant.r1.service import R1Authority, R1Error
    from restaurant.r1.sql_repository import SQLR1Repository
    from scripts import swes_r3_wnd_test_menu_publish as menu
    from scripts import swes_r4_wnd_phase1_bundle as bundle
    from shared_operations.so1.sql_repository import SQLSO1Repository

    pre = target.execute(disposable_url, "dry-run", hosted=False)
    if pre["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)
    mp = menu.publish(disposable_url, apply=False, hosted=False)
    if mp["before"]["r2_restaurant_menu_sections"] == 0:
        menu.publish(disposable_url, apply=True, hosted=False)
    engine = create_engine(disposable_url)
    try:
        with engine.connect() as check:
            mode_count = int(check.execute(text(
                "SELECT count(*) FROM r1_restaurant_service_modes "
                "WHERE tenant_id=:t AND mode_code='takeaway'"
            ), {"t": target.TENANT}).scalar_one())
        if mode_count == 0:
            bundle.execute(disposable_url, apply=True, hosted=False)
        with Session(engine) as session:
            so1 = SQLSO1Repository(session)
            authority = R1Authority(
                SQLR1Repository(session),
                resource_resolver=lambda *_a: None,
                party_resolver=lambda *_a: None,
                identity_resolver=lambda *_a: None,
                offer_resolver=so1.offer,
                atomic_unit_resolver=so1.atomic_unit,
                price_resolver=so1.price,
                reservation_resolver=lambda *_a: None,
                authorize=lambda *_a: True,  # disposable-only authority fixture
            )
            now = datetime.now(timezone.utc)
            command = OpenOrder(
                "swes-wnd05-open",target.TENANT,"SWES-WND05-LOCAL",
                "takeaway","whatsapp",now,
            )
            order = authority.open_order(command)
            assert order.status is OrderStatus.OPEN
            assert order.mode_code == "takeaway"
            assert order.source_channel_code == "whatsapp"
            assert not order.lines
            assert authority.open_order(command).public_id == order.public_id
            line_command = AddLine(
                "swes-wnd05-add",target.TENANT,order.public_id,
                order.row_version,R1TargetType.ATOMIC_UNIT,
                target.IDS["unit"],target.IDS["price"],Decimal(1),now,
            )
            completed = authority.add_line(line_command)
            assert len(completed.lines) == 1
            assert completed.lines[0].unit_price_snapshot == Decimal(1000)
            assert completed.lines[0].currency == "XAF"
            assert completed.lines[0].quantity == Decimal(1)
            assert authority.add_line(line_command).row_version == completed.row_version
            with pytest.raises(R1Error, match="R1_ORDER_LINE_CONFLICT"):
                authority.add_line(AddLine(
                    "swes-wnd05-stale",target.TENANT,order.public_id,
                    order.row_version,R1TargetType.ATOMIC_UNIT,
                    target.IDS["unit"],target.IDS["price"],Decimal(1),now,
                ))
            session.rollback()  # no persistent even-disposable canonical order
        with engine.connect() as check:
            assert check.execute(text(
                "SELECT count(*) FROM public.r1_restaurant_orders "
                "WHERE tenant_id=:t AND order_code='SWES-WND05-LOCAL'"
            ), {"t":target.TENANT}).scalar_one() == 0
    finally:
        engine.dispose()

def test_swes_wnd_phase1_independent_readback_on_disposable_pg17(disposable_url):
    """Independent read-only join after actual synthetic bundle on PostgreSQL."""
    import importlib.util

    from scripts import swes_r3_wnd_test_menu_publish as menu
    from scripts import swes_r4_wnd_phase1_bundle as bundle

    pre = target.execute(disposable_url, "dry-run", hosted=False)
    if pre["before"]["tenants"] == 0:
        target.execute(disposable_url, "apply", hosted=False)
    state = menu.publish(disposable_url, apply=False, hosted=False)
    if state["before"]["r2_restaurant_menu_sections"] == 0:
        menu.publish(disposable_url, apply=True, hosted=False)
    bundle.execute(disposable_url, apply=True, hosted=False)

    script = (
        Path(__file__).resolve().parents[4]
        / "PCR_SHARED_EVIDENCE_INBOX"
        / "V17"
        / "Wave1"
        / "03_lanes"
        / "xbos_wnd"
        / "outbox"
        / "SWES_R1_CONDITIONAL_BATCHES_20261030"
        / "34_SWES_R4_WND_PHASE1_HOSTED_DURABLE_READBACK_R0.py"
    )
    spec = importlib.util.spec_from_file_location("wnd_phase1_readback", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = module.verify(disposable_url, hosted=False)
    assert observed["durable_phase1_pass"] is True
    assert observed["published_menu_price_joins"] == 1
    assert observed["binding_scope_id"] == observed["binding_location_id"]
    assert observed["database_writes"] is False
