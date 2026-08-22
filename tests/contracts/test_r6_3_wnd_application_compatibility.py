from __future__ import annotations
import json
from pathlib import Path

from restaurant.r6.application_compatibility import (
    assert_required_routes,
    openapi_route_set,
    schema_fingerprint,
    validate_uat_evidence,
)

ROOT = Path(__file__).resolve().parents[2]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_r6_3_authority_is_non_cutover_and_pins_reference_release():
    authority = load("contracts/restaurant/v1/r6_3_application_compatibility_authority.json")
    assert authority["source_checkpoint"] == "9a8c69dfb0caf18fe010d858caceef84b863a4c2"
    assert authority["production_write_authorized"] is False
    assert authority["writer_routing"] == "unchanged"
    assert authority["live_cutover_authorized"] is False
    assert authority["reference_backend_commit"].startswith("b60a71d")
    assert authority["reference_frontend_commit"].startswith("f47f574")
    assert authority["candidate_database"] == "xbos_r6_3_candidate"


def test_r6_3_reference_contract_covers_operational_surfaces():
    contract = load("contracts/restaurant/v1/r6_3_reference_application_contract.json")
    routes = {(row["method"], row["path"]) for row in contract["required_openapi_routes"]}
    required = {
        ("GET", "/kernel/catalog/summary"),
        ("GET", "/kernel/orders/"),
        ("GET", "/kernel/inventory/"),
        ("GET", "/kernel/payments/activity"),
        ("GET", "/kernel/accounting/accounts/ar"),
        ("GET", "/kernel/customers"),
        ("GET", "/kernel/reports/debt"),
    }
    assert required <= routes
    assert {"DINE_IN", "TAKEAWAY", "DELIVERY"} <= set(
        contract["frontend_source_markers"]["src/modules/sales/SalesAndCartScreen.tsx"]
    )


def test_openapi_route_helper():
    schema = {"paths": {"/x": {"get": {}}, "/y": {"post": {}, "parameters": []}}}
    assert openapi_route_set(schema) == {("GET", "/x"), ("POST", "/y")}
    assert_required_routes(schema, [{"method": "GET", "path": "/x"}])


def test_schema_fingerprint_is_order_independent():
    rows = [
        {"table_name": "b", "column_name": "x", "data_type": "integer", "is_nullable": "NO", "column_default": None},
        {"table_name": "a", "column_name": "y", "data_type": "text", "is_nullable": "YES", "column_default": None},
    ]
    assert schema_fingerprint(rows) == schema_fingerprint(list(reversed(rows)))


def test_visual_uat_requires_every_frozen_item():
    matrix = load("contracts/restaurant/v1/r6_3_uat_matrix.json")
    evidence = {"status": "PASS", "items": {row["id"]: "PASS" for row in matrix["items"]}}
    validate_uat_evidence(evidence, matrix)


def test_r6_3_subprocess_capture_is_utf8_safe(monkeypatch):
    import scripts.verify_r6_3_wnd_application_compatibility as r63

    seen = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr(r63.subprocess, "run", fake_run)
    result = r63._run_text(["dummy"])
    assert result.stdout == "ok"
    assert seen["text"] is True
    assert seen["encoding"].lower().replace("_", "-") == "utf-8"
    assert seen["errors"] == "replace"


def test_r6_3_uat_supervisor_uses_candidate_only_and_persistent_logs():
    source = (ROOT / "scripts/start_r6_3_uat_runtime.py").read_text(encoding="utf-8")
    assert "r63.CANDIDATE_DATABASE" in source
    assert "r63._backend_env()" in source
    assert "r6_3_uat_backend.log" in source
    assert "r6_3_uat_frontend.log" in source
    assert "r6_3_uat_runtime_pids.json" in source
    assert "PRODUCTION_WRITES=NONE" in source
    assert "LIVE_CUTOVER_AUTHORIZED=NO" in source


def test_r6_3_uat_runtime_ports_are_explicit_and_stable():
    import scripts.verify_r6_3_wnd_application_compatibility as r63

    assert r63.BACKEND_PORT == 8002
    assert r63.FRONTEND_PORT == 5174

    source = (ROOT / "scripts/start_r6_3_uat_runtime.py").read_text(encoding="utf-8")
    assert "BACKEND_PORT = 8002" in source
    assert "FRONTEND_PORT = 5174" in source
    assert "r63.FRONTEND_PORT" not in source
    assert "r63.BACKEND_PORT" not in source


def test_r6_3_legacy_inventory_writer_compatibility_migration_is_narrow():
    version = (ROOT / "alembic_neutral/versions/r63_legacy_inventory_writer_compat_044.py").read_text(encoding="utf-8")
    up = (ROOT / "alembic_neutral/sql/r63_legacy_inventory_writer_compat_up.sql").read_text(encoding="utf-8")
    down = (ROOT / "alembic_neutral/sql/r63_legacy_inventory_writer_compat_down.sql").read_text(encoding="utf-8")

    assert 'revision = "r63_legacy_inventory_writer_compat_044"' in version
    assert 'down_revision = "r2_restaurant_menu_fulfillment_043"' in version
    assert "BEFORE INSERT ON public.inventory_items" in up
    assert "BEFORE INSERT ON public.inventory_movements" in up
    assert "NEW.stock_location_id" in up
    assert "NEW.occurred_at" in up
    assert "NEW.reason_code" in up
    assert "NEW.source_reference" in up
    assert "quantity_delta :=" not in up
    assert "movement_type :=" not in up
    assert "DROP TRIGGER IF EXISTS trg_r63_legacy_inventory_movement_fill_neutral_fields" in down


def test_r6_3_contract_identifies_inventory_as_shared_failed_write_boundary():
    contract = load("contracts/restaurant/v1/r6_3_legacy_inventory_writer_compatibility.json")
    assert contract["revision"] == "r63_legacy_inventory_writer_compat_044"
    assert contract["production_write_authorized"] is False
    assert contract["writer_routing"] == "unchanged"
    assert contract["legacy_writer_retirement"] == "not_executed"
    assert contract["live_cutover_authorized"] is False
    assert contract["problem_proven_by_visual_uat"]["shared_legacy_boundary"].startswith("inventory reservation")


def test_r6_3_uat_observer_captures_5xx_without_changing_inner_app():
    source = (ROOT / "scripts/r6_3_uat_host_template.py").read_text(encoding="utf-8")
    assert "from main import app as _inner_app" in source
    assert "class ObservedApp" in source
    assert '"event": "exception"' in source
    assert '"event": "http_5xx"' in source
    assert "traceback.format_exc()" in source
    assert "with ERROR_FILE.open" in source
    assert "app = ObservedApp(_inner_app)" in source

    launcher = (ROOT / "scripts/start_r6_3_uat_runtime.py").read_text(encoding="utf-8")
    assert '"r6_3_uat_host:app"' in launcher
    assert "r6_3_uat_errors.jsonl" in launcher


def test_r6_3_uat_launcher_tracks_direct_vite_node_process():
    source = (ROOT / "scripts/start_r6_3_uat_runtime.py").read_text(encoding="utf-8")
    assert 'shutil.which("node.exe")' in source
    assert '"node_modules" / "vite" / "bin" / "vite.js"' in source
    assert '"npm.cmd"' not in source
    assert '"run",' not in source
    assert 'if _http_ok(f"http://127.0.0.1:{FRONTEND_PORT}/"):' in source


def test_r6_3_verifier_imports_alembic_command_for_candidate_upgrade():
    source = (ROOT / "scripts/verify_r6_3_wnd_application_compatibility.py").read_text(encoding="utf-8")
    assert "from alembic import command" in source
    assert "command.upgrade(" in source


def test_r6_3_legacy_inventory_probe_registers_full_wnd_model_registry():
    source = (ROOT / "scripts/verify_r6_3_wnd_application_compatibility.py").read_text(encoding="utf-8")
    probe_start = source.index("def _legacy_inventory_writer_probe")
    probe_end = source.index("def _runtime_smoke", probe_start)
    probe = source[probe_start:probe_end]
    assert "import core.models_import" in probe
    assert probe.index("import core.models_import") < probe.index(
        "from core.domain.inventory.models import InventoryItem, InventoryMovement"
    )


def test_r6_3_legacy_inventory_probe_uses_frozen_production_branch_identity():
    import restaurant.r6 as r6

    assert r6.PRODUCTION_TENANT_ID == 2
    assert r6.PRODUCTION_BRANCH_ID == 1

    source = (ROOT / "scripts/verify_r6_3_wnd_application_compatibility.py").read_text(encoding="utf-8")
    probe_start = source.index("def _legacy_inventory_writer_probe")
    probe_end = source.index("def _runtime_smoke", probe_start)
    probe = source[probe_start:probe_end]

    assert 'R6_3_PROBE_TENANT_ID' in probe
    assert 'R6_3_PROBE_BRANCH_ID' in probe
    assert 'str(r61.PRODUCTION_TENANT_ID)' in probe
    assert 'str(r61.PRODUCTION_BRANCH_ID)' in probe
    assert 'InventoryItem.branch_id == 3' not in probe


def test_r6_3_accepted_uat_closure_avoids_interactive_token_capture():
    source = (ROOT / "scripts/close_r6_3_after_accepted_uat.py").read_text(encoding="utf-8")
    assert 'TOKEN = "ACCEPT" + "-" + "R6.3" + "-" + "WND" + "-" + "UAT"' in source
    assert "r63._record_uat(TOKEN)" in source
    assert "r63._final()" in source
    assert '"XBOS_R6_3_RUN_ACCEPTANCE.cmd"' in source
    assert "R6_3_SINGLE_GATE=PASS" in source
    assert "XBOS_R6_3_CLOSE_RESULT.txt" in source

    wrapper = (ROOT / "XBOS_R6_3_CLOSE_ACCEPTED_UAT.cmd").read_text(encoding="utf-8")
    assert "set /p" not in wrapper.lower()
    assert "close_r6_3_after_accepted_uat.py" in wrapper
    assert "notepad.exe" in wrapper
