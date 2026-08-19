from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C = ROOT / "contracts/restaurant/v1"


def load(name):
    return json.loads((C / name).read_text(encoding="utf-8"))


def test_r0_is_boundary_only_and_no_migration_or_runtime_writer_is_authorized():
    x = load("r0_public_interfaces.json")
    assert x["migration_added"] is False
    assert x["database_tables_added"] == []
    assert x["runtime_interfaces_added"] == []
    assert "No runtime Restaurant API" in x["law"]


def test_wnd_is_evidence_not_restaurant_capability_ceiling():
    x = load("r0_restaurant_surface_inventory.json")
    assert "not the restaurant-industry capability ceiling" in x["source"]["evidence_law"]
    missing = set(x["missing_or_not_proven_by_wnd_but_required_for_restaurant_pack"])
    assert "dining areas and table resources" in missing
    assert "reservation/waitlist composition with SO10" in missing
    assert "station-aware kitchen/bar routing" in missing
    assert "recipe/preparation definitions with yield and waste" in missing


def test_authority_map_does_not_duplicate_neutral_truth():
    rows = {x["capability"]: x for x in load("r0_authority_classification.json")["classifications"]}
    assert rows["atomic units/catalog/offers/pricing"]["owner"] == "SO1"
    assert rows["inventory quantities/reservations/movements"]["owner"] == "SO3"
    assert rows["scheduling/reservations/service execution"]["owner"] == "SO10"
    assert rows["obligations/payments/allocations/receivables/settlement/journals/reconciliation"]["owner"] == "Neutral Finance"
    assert rows["restaurant order lifecycle"]["owner"] == "Restaurant Pack"


def test_restaurant_aggregates_are_operational_not_financial_authorities():
    x = load("r0_aggregate_event_catalog.json")
    codes = {a["code"] for a in x["aggregate_boundaries"]}
    assert codes == {"restaurant_order", "restaurant_service_session", "restaurant_tab", "preparation_ticket", "restaurant_preparation_spec"}
    assert all(e["financial_effect"] == "NONE" for e in x["event_catalog"])
    tab = next(a for a in x["aggregate_boundaries"] if a["code"] == "restaurant_tab")
    assert "amount owed" in tab["does_not_own"]


def test_track_a_stock_and_finance_invariants_are_carried_forward():
    rows = {x["id"]: x for x in load("r0_wnd_production_invariants.json")["invariants"]}
    assert len(rows) == 14
    assert "not new income" in rows["WND-INV-01"]["truth"]
    assert "exactly one inventory quantity effect" in rows["WND-INV-05"]["truth"]
    assert "must not deduct stock again" in rows["WND-INV-06"]["truth"]
    assert "Non-stock charges never touch inventory" in rows["WND-INV-09"]["truth"]
    assert "must not become an invented universal costing model" in rows["WND-INV-14"]["truth"]


def test_wnd_specific_time_and_literals_move_to_profile_configuration():
    x = load("r0_wnd_extraction_plan.json")
    moves = {m["current"]: m for m in x["moves"]}
    assert moves["08:00→08:00 business window and 18:00 attribution"]["target"] == "PC4 business-time/configuration resolved for WND"
    assert "tables" in x["do_not_infer_from_wnd_absence"]
    assert "reservations" in x["do_not_infer_from_wnd_absence"]


def test_wnd_production_evidence_identity_and_counts_are_frozen():
    x = load("r0_restaurant_surface_inventory.json")
    s = x["source"]
    assert s["wnd_final_tag"] == "wnd-track-a-final-accepted-20260818"
    assert s["wnd_backend_head"] == "651e83a40f9a69f496def3a599c94dbd63d97ef3"
    assert s["wnd_frontend_head"] == "50583b1a3fcc67e7f817ea92121b94147fbd5984"
    assert x["wnd_production_counts"]["orders"] == 8171
    assert x["wnd_production_counts"]["order_items"] == 17359
    assert x["wnd_production_counts"]["inventory_movements"] == 37534


def test_r0_source_checkpoint_is_exact_semantic_hardening_freeze():
    x = load("r0_restaurant_surface_inventory.json")["source"]
    assert x["neutral_source_commit"] == "64eb3e98135261ef20cd90622c1fd64bf24c99d8"
    assert x["canonical_migration_head"] == "semantic_classification_hardening_041"


def test_r0_development_verifier_bootstraps_repository_root_for_database_import():
    source = (ROOT / "scripts/verify_r0_restaurant_domain_extraction.py").read_text(encoding="utf-8")
    assert "import sys" in source
    assert "if str(ROOT) not in sys.path:" in source
    assert "sys.path.insert(0, str(ROOT))" in source
    assert "from database import engine" in source
