"""Source-faithful SWES TEST fixture rehearsal on disposable loopback PG17 ONLY.

Creates a temporary local PGDATA and database, replays neutral migrations,
proves atomic rollback on injected SQL failure, verifies exact successful
fixture and duplicate refusal, and shuts down the temporary cluster.
Never connects to Render and never calls providers.
"""
from __future__ import annotations

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
