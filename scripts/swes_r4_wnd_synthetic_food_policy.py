"""PCR SWES WND-02: bounded synthetic-only kitchen classification.

No production services, taxonomy tree creation, inventory position,
payment, PA onboarding or role operations. --apply must be explicitly
operator-attested; default mode is read-only. Guard exact original metadata,
row_version, zero existing inventory/mapping, and the intended tenant/SKU.
"""
from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine, text

TENANT = 910001
SKU = "SWES-R2-CATALOG-ITEM"
DATABASE = "wnd_xafpay_demo_austin_db"
ACTOR = "wnd_xafpay_demo_austin_db_user"
PREVIOUS = {"campaign": "PCR_V17_SWES_R2", "test_only": True}
EXPECTED = {
    **PREVIOUS,
    "inventory_family": "kitchen",
    "category": "food",
    "track_stock": True,
    "cost_mode": "expense_allocated",
    "allow_negative_stock": True,
    "disable_when_out": False,
    "synthetic_classification": "prepared_food",
}


def qualify(url: str, *, apply: bool, hosted: bool):
    if hosted and apply and os.environ.get(
        "SWES_WND_OWNER_ATTESTED_SYNTHETIC_ONLY"
    ) != "I_CONFIRM_TEST_ONLY":
        raise RuntimeError("HOLD_OWNER_TEST_ATTESTATION")
    engine = create_engine(url, pool_pre_ping=False)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.exec_driver_sql(
                    "SET TRANSACTION READ WRITE"
                    if apply else "SET TRANSACTION READ ONLY"
                )
                conn.exec_driver_sql("SET LOCAL statement_timeout='8000ms'")
                conn.exec_driver_sql("SET LOCAL lock_timeout='500ms'")
                identity = tuple(conn.execute(text(
                    "SELECT current_database(), current_user, session_user"
                )).one())
                if hosted and identity != (DATABASE, ACTOR, ACTOR):
                    raise RuntimeError("HOLD_DATABASE_OR_PRINCIPAL")
                if not hosted and (
                    engine.url.host not in ("127.0.0.1", "localhost")
                    or engine.url.database != "swes_r2_wnd_bootstrap_disposable"
                ):
                    raise RuntimeError("HOLD_NONDISPOSABLE_DATABASE")
                rows = conn.execute(text("""
                    SELECT id,public_id,sku,unit_type,is_active,meta,row_version
                    FROM public.atomic_units
                    WHERE tenant_id=:t AND sku=:sku
                """), {"t": TENANT, "sku": SKU}).mappings().all()
                if len(rows) != 1:
                    raise RuntimeError("HOLD_MISSING_OR_DUPLICATE_UNIT")
                unit = dict(rows[0])
                if unit["unit_type"] != "product" or unit["is_active"] is not True:
                    raise RuntimeError("HOLD_WRONG_ITEM_TYPE_OR_STATUS")
                if unit["meta"] != PREVIOUS:
                    raise RuntimeError("HOLD_PREVIOUS_METADATA_MISMATCH")
                assignments = int(conn.execute(text("""
                    SELECT count(*) FROM public.atomic_unit_taxonomy
                    WHERE atomic_unit_id=:id
                """), {"id": unit["id"]}).scalar_one())
                positions = int(conn.execute(text("""
                    SELECT count(*) FROM public.inventory_items
                    WHERE tenant_id=:t AND atomic_unit_id=:id
                """), {"t": TENANT, "id": unit["id"]}).scalar_one())
                if assignments or positions:
                    raise RuntimeError("HOLD_EXISTING_STOCK_OR_TAXONOMY")
                data = {
                    "mode": "apply" if apply else "read_only",
                    "tenant": TENANT,
                    "sku": SKU,
                    "before_row_version": unit["row_version"],
                    "initial_taxonomy_assignments": assignments,
                    "initial_stock_positions": positions,
                    "original_meta": unit["meta"],
                    "target_meta": EXPECTED,
                    "provider_calls": 0,
                }
                if apply:
                    result = conn.execute(text("""
                        UPDATE public.atomic_units
                        SET meta=CAST(:meta AS jsonb),
                            row_version=row_version+1
                        WHERE id=:id AND tenant_id=:t
                          AND sku=:sku AND row_version=:version
                          AND meta=CAST(:previous AS jsonb)
                        RETURNING row_version,meta
                    """), {
                        "id": unit["id"], "t": TENANT, "sku": SKU,
                        "version": unit["row_version"],
                        "previous": json.dumps(PREVIOUS, sort_keys=True),
                        "meta": json.dumps(EXPECTED, sort_keys=True),
                    }).mappings().all()
                    if len(result) != 1 or dict(result[0])["meta"] != EXPECTED:
                        raise RuntimeError("HOLD_CLASSIFICATION_UPDATE_CONFLICT")
                    data["after_row_version"] = result[0]["row_version"]
                    data["classification_applied"] = True
                else:
                    data["database_writes"] = False
            return data
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hosted", action="store_true")
    a = parser.parse_args()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("HOLD_DATABASE_URL")
    print(json.dumps(qualify(url, apply=a.apply, hosted=a.hosted),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
