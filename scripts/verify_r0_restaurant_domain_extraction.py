#!/usr/bin/env python3
"""Verify R0 Restaurant-domain extraction boundary and release artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONTRACTS = ROOT / "contracts/restaurant/v1"
SOURCE = "64eb3e98135261ef20cd90622c1fd64bf24c99d8"
SOURCE_ARCHIVE_SHA256 = "55cb4fff4e984ab2b298bdc93745b1e1f591c9c201ff27a4dabfc49e2c24d5a3"
SOURCE_ARCHIVE_SIZE = 5990823
HEAD = "semantic_classification_hardening_041"
TEXT_SUFFIXES = {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}

FROZEN_FINGERPRINTS = {
    "shared_operations/so1/service.py": "5ede283f303f0e05f107de699e351fe5ef875b472ba81c407e873a4508fd19da",
    "shared_operations/so3/service.py": "179a7634235863bf9221d07590b99587120803ea84a9bb88392ea40261d2a116",
    "shared_operations/so8/service.py": "acba25f82b73aaea53d723694305b9a139dc3fe3db1eb1a1be10df4a32ec04ab",
    "shared_operations/so10/service.py": "880f69402bbf81faf17964ecfbe49c28c6cb23ed374970f0ea864a98e276a930",
    "pack_platform/service.py": "4ed2eb4595baf793138c87d67543274f1990254be4c1e844fdcecc57aafc2a68",
    "platform_admin/service.py": "951e8331dcc8cc4f8023b2e6419e6bc43785ad9c325c26ad1e3a176c06d5b10d",
    "core/platform/semantics/classification_hardening/service.py": "a9817c70d01c4f895a1f2c72ab112c5c2e81ba7120377b0be9f057ea0b974268",
    "core/domain/finance/transactional_event_engine.py": "fb138dc0f129cbbea42a9381d812b40e89dea23b4df138b759fe2fe9ff74fba0",
    "core/domain/orders/service.py": "42c6ea1e5f1c4b95cfdceeb7f272f6c5c1659ded67de2771255c49b3f5ea2ae1",
    "core/domain/inventory/service.py": "014896d7d27428a761a96be07542452405c241a02469a600811a465f70606bae",
    "core/domain/sales/service.py": "b554580d2f0d32f904511a96958864c9313823439a44b4be890f8d0237527fdb",
}


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def canonical_sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify_manifest() -> int:
    manifest = load("r0_release_manifest.json")
    if manifest["source_checkpoint"] != SOURCE:
        raise RuntimeError("R0_SOURCE_CHECKPOINT")
    if manifest["source_archive_sha256"] != SOURCE_ARCHIVE_SHA256 or manifest["source_archive_size"] != SOURCE_ARCHIVE_SIZE:
        raise RuntimeError("R0_SOURCE_ARCHIVE_IDENTITY")
    if manifest["accepted_migration_head"] != HEAD or manifest["migration_count"] != 0:
        raise RuntimeError("R0_MIGRATION_BOUNDARY")
    entries = manifest["artifacts"]
    if manifest["artifact_count"] != len(entries) or len({x["path"] for x in entries}) != len(entries):
        raise RuntimeError("R0_RELEASE_MANIFEST_COUNT")
    for item in entries:
        path = ROOT / item["path"]
        if not path.is_file():
            raise RuntimeError("R0_RELEASE_ARTIFACT_MISSING=" + item["path"])
        if canonical_sha(path) != item["sha256"]:
            raise RuntimeError("R0_RELEASE_ARTIFACT_CHANGED=" + item["path"])
    return len(entries)


def static_verify() -> dict:
    inventory = load("r0_restaurant_surface_inventory.json")
    authority = load("r0_authority_classification.json")
    aggregates = load("r0_aggregate_event_catalog.json")
    invariants = load("r0_wnd_production_invariants.json")
    plan = load("r0_wnd_extraction_plan.json")
    interfaces = load("r0_public_interfaces.json")

    source = inventory["source"]
    if source["neutral_source_commit"] != SOURCE or source["neutral_source_archive_sha256"] != SOURCE_ARCHIVE_SHA256:
        raise RuntimeError("R0_NEUTRAL_SOURCE_EVIDENCE")
    if source["wnd_final_tag"] != "wnd-track-a-final-accepted-20260818":
        raise RuntimeError("R0_WND_FINAL_TAG")
    if source["evidence_law"].find("not the restaurant-industry capability ceiling") < 0:
        raise RuntimeError("R0_WND_SPECIMEN_LAW")

    if inventory["wnd_production_counts"]["orders"] != 8171 or inventory["wnd_production_counts"]["inventory_movements"] != 37534:
        raise RuntimeError("R0_WND_EVIDENCE_COUNTS")
    missing = set(inventory["missing_or_not_proven_by_wnd_but_required_for_restaurant_pack"])
    if not {"dining areas and table resources", "configurable service modes", "station-aware kitchen/bar routing", "recipe/preparation definitions with yield and waste"}.issubset(missing):
        raise RuntimeError("R0_WORLD_RESTAURANT_GAPS")

    rows = {x["capability"]: x for x in authority["classifications"]}
    required_owners = {
        "atomic units/catalog/offers/pricing": "SO1",
        "inventory quantities/reservations/movements": "SO3",
        "scheduling/reservations/service execution": "SO10",
        "obligations/payments/allocations/receivables/settlement/journals/reconciliation": "Neutral Finance",
        "restaurant order lifecycle": "Restaurant Pack",
        "WND 08:00-08:00 calendar and 18:00 attribution": "WND tenant/template config via PC4/PK",
    }
    for capability, owner in required_owners.items():
        if rows.get(capability, {}).get("owner") != owner:
            raise RuntimeError("R0_AUTHORITY_OWNER=" + capability)

    aggregate_codes = {x["code"] for x in aggregates["aggregate_boundaries"]}
    if aggregate_codes != {"restaurant_order", "restaurant_service_session", "restaurant_tab", "preparation_ticket", "restaurant_preparation_spec"}:
        raise RuntimeError("R0_AGGREGATE_BOUNDARY")
    if any(x["financial_effect"] != "NONE" for x in aggregates["event_catalog"]):
        raise RuntimeError("R0_EVENT_FINANCIAL_AUTHORITY_LEAK")
    if "Canonical Finance commands" not in aggregates["financial_handoff_law"]:
        raise RuntimeError("R0_FINANCIAL_HANDOFF_LAW")

    ids = {x["id"] for x in invariants["invariants"]}
    if ids != {f"WND-INV-{n:02d}" for n in range(1, 15)}:
        raise RuntimeError("R0_WND_INVARIANT_COVERAGE")
    inv = {x["id"]: x for x in invariants["invariants"]}
    if "exactly one inventory quantity effect" not in inv["WND-INV-05"]["truth"]:
        raise RuntimeError("R0_STOCK_EXACTLY_ONCE")
    if "must not become an invented universal costing model" not in inv["WND-INV-14"]["truth"]:
        raise RuntimeError("R0_COSTING_BOUNDARY")

    moves = {x["current"]: x for x in plan["moves"]}
    if "08:00→08:00 business window and 18:00 attribution" not in moves:
        raise RuntimeError("R0_WND_TIME_EXTRACTION")
    if "tables" not in plan["do_not_infer_from_wnd_absence"]:
        raise RuntimeError("R0_WND_ABSENCE_NOT_STANDARD")

    if interfaces["migration_added"] or interfaces["database_tables_added"] or interfaces["runtime_interfaces_added"]:
        raise RuntimeError("R0_RUNTIME_OR_SCHEMA_CHANGE")
    if "No runtime Restaurant API" not in interfaces["law"]:
        raise RuntimeError("R0_BOUNDARY_ONLY")

    # R0 must not modify the neutral authorities or legacy compatibility writers it is classifying.
    for relative, expected in FROZEN_FINGERPRINTS.items():
        path = ROOT / relative
        if not path.is_file() or canonical_sha(path) != expected:
            raise RuntimeError("R0_FROZEN_SOURCE_CHANGED=" + relative)

    # R0 itself added no runtime implementation. A later Restaurant milestone may
    # consume the frozen R0 boundary, but only as an explicit canonical descendant.
    forbidden_runtime = [ROOT / "core/domain/restaurant", ROOT / "shared_operations/restaurant"]
    if any(p.exists() for p in forbidden_runtime):
        raise RuntimeError("R0_RUNTIME_RESTAURANT_SOURCE_MISPLACED")
    restaurant_runtime = ROOT / "restaurant"
    if restaurant_runtime.exists():
        if not (ROOT / "contracts/restaurant/v1/r1_service_operation_authority.json").is_file():
            raise RuntimeError("R0_UNGOVERNED_RESTAURANT_DESCENDANT")
        if not (ROOT / "alembic_neutral/versions/r1_restaurant_service_operation_042.py").is_file():
            raise RuntimeError("R0_RESTAURANT_DESCENDANT_LINEAGE_MISSING")
    if any((ROOT / "alembic_neutral/versions").glob("r0*.py")) or any((ROOT / "alembic_neutral/sql").glob("r0*.sql")):
        raise RuntimeError("R0_MIGRATION_PRESENT")

    artifacts = verify_manifest()
    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "accepted_migration_head": HEAD,
        "migration": "NONE",
        "restaurant_surface_inventory": "PASS",
        "authority_classification": "PASS",
        "aggregate_boundaries": "PASS",
        "event_catalog": "PASS",
        "wnd_invariants": 14,
        "wnd_specimen_not_standard": "PASS",
        "tenant_literal_plan": "PASS",
        "missing_restaurant_capabilities_reserved": "PASS",
        "runtime_change": "NONE",
        "finance": "UNCHANGED",
        "shared_operations": "UNCHANGED",
        "platform_core": "UNCHANGED",
        "pack_platform": "UNCHANGED",
        "platform_admin": "UNCHANGED",
        "release_artifacts": artifacts,
    }


def development_head_verify() -> dict:
    from sqlalchemy import text
    from database import engine
    with engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if head != HEAD:
            raise RuntimeError("R0_DEVELOPMENT_HEAD=" + str(head))
    return {"development_head": head, "database_action": "READ_ONLY"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--development", action="store_true")
    args = p.parse_args()
    try:
        result = static_verify()
        if args.development:
            result.update(development_head_verify())
    except Exception as exc:
        print("R0_VERIFY=FAIL\n" + str(exc))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R0_VERIFY=PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
