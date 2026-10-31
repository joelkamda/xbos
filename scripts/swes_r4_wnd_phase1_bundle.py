"""SWES R4 WND 02-04: one TEST-only, rollback-safe hosted phase-one bundle.

Defaults read-only. Qualified only for WND Austin tenant 910001, one exact
synthetic unit and catalog binding. No PA state changes, service identity,
real stock movement, order, provider calls, or paid hosting upgrades.
"""
from __future__ import annotations

import argparse
import json
import os
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, text

T = 910001
DB = "wnd_xafpay_demo_austin_db"
ACTOR = "wnd_xafpay_demo_austin_db_user"
ROOT = "xafpay:swes:r2:wnd-austin:"
KEY = lambda name: str(uuid5(NAMESPACE_URL, ROOT + name))
SKU = "SWES-R2-CATALOG-ITEM"
PREVIOUS = {"campaign": "PCR_V17_SWES_R2", "test_only": True}
FOOD_META = {
    **PREVIOUS, "category": "food", "inventory_family": "kitchen",
    "track_stock": True, "cost_mode": "expense_allocated",
    "allow_negative_stock": True, "disable_when_out": False,
    "synthetic_classification": "prepared_food",
}
TAKEAWAY_META = {"test_only": True, "campaign": "PCR_V17_SWES_R4",
                 "fulfillment": "virtual_pickup"}


def _qualified(conn):
    identity = tuple(conn.execute(text(
        "SELECT current_database(),current_user,session_user"
    )).one())
    unit = conn.execute(text("""
        SELECT id,public_id,meta,unit_type,is_active,row_version
        FROM public.atomic_units WHERE tenant_id=:t AND sku=:sku
    """), {"t": T, "sku": SKU}).mappings().all()
    binding = conn.execute(text("""
        SELECT id,public_id,location_id,price_code,currency,scope_type,
               scope_id,row_version,active
        FROM public.restaurant_customer_catalog_read_bindings
        WHERE tenant_id=:t
    """), {"t": T}).mappings().all()
    menu_sections = int(conn.execute(text(
        "SELECT count(*) FROM public.r2_restaurant_menu_sections WHERE tenant_id=:t"
    ), {"t": T}).scalar_one())
    menu_entries = int(conn.execute(text(
        "SELECT count(*) FROM public.r2_restaurant_menu_section_entries WHERE tenant_id=:t"
    ), {"t": T}).scalar_one())
    modes = int(conn.execute(text(
        "SELECT count(*) FROM public.r1_restaurant_service_modes "
        "WHERE tenant_id=:t AND mode_code='takeaway'"
    ), {"t": T}).scalar_one())
    orders = int(conn.execute(text(
        "SELECT count(*) FROM public.r1_restaurant_orders WHERE tenant_id=:t"
    ), {"t": T}).scalar_one())
    if len(unit) != 1 or len(binding) != 1:
        raise RuntimeError("HOLD_UNIT_OR_BINDING_NOT_UNIQUE")
    u, b = dict(unit[0]), dict(binding[0])
    taxonomies = int(conn.execute(text(
        "SELECT count(*) FROM public.atomic_unit_taxonomy WHERE atomic_unit_id=:id"
    ), {"id": u["id"]}).scalar_one())
    inventory = int(conn.execute(text(
        "SELECT count(*) FROM public.inventory_items "
        "WHERE tenant_id=:t AND atomic_unit_id=:id"
    ), {"t": T, "id": u["id"]}).scalar_one())
    loc = int(conn.execute(text("""
        SELECT count(*) FROM public.locations
        WHERE tenant_id=:t AND id=:id AND active=true
    """), {"t": T, "id": b["location_id"]}).scalar_one())
    merchant = int(conn.execute(text(
        "SELECT count(*) FROM public.pa_merchants WHERE tenant_id=:t "
        "AND public_id=CAST(:m AS uuid) AND administration_state='registered'"
    ), {"t": T, "m": KEY("merchant")}).scalar_one())
    result = {
        "database": identity[0], "tenant": T,
        "unit_meta": u["meta"], "unit_row_version": u["row_version"],
        "binding_scope": b["scope_type"], "binding_scope_id": b["scope_id"],
        "binding_row_version": b["row_version"],
        "takeaway_modes": modes, "orders": orders,
        "menu_sections": menu_sections, "menu_entries": menu_entries,
        "taxonomy_assignments": taxonomies, "inventory_positions": inventory,
    }
    if (
        u["public_id"] != uuid5(NAMESPACE_URL, ROOT + "unit")
        or b["public_id"] != uuid5(NAMESPACE_URL, ROOT + "catalog_binding")
        or u["unit_type"] != "product" or u["is_active"] is not True
        or u["meta"] != PREVIOUS
        or not b["active"] or b["scope_type"] != "tenant"
        or b["scope_id"] is not None or b["price_code"] != "swes-retail"
        or b["currency"] != "XAF" or modes != 0 or orders != 0
        or taxonomies != 0 or inventory != 0
        or menu_sections != 1 or menu_entries != 1
        or loc != 1 or merchant != 1
    ):
        raise RuntimeError("HOLD_WND_PHASE1_HOSTED_PRESTATE_MISMATCH")
    return identity, u, b, result


def execute(url: str, *, apply: bool, hosted: bool):
    if apply and hosted and os.getenv(
        "SWES_WND_OWNER_ATTESTED_SYNTHETIC_ONLY"
    ) != "I_CONFIRM_TEST_ONLY":
        raise RuntimeError("HOLD_OWNER_ATTESTATION")
    engine = create_engine(url, pool_pre_ping=False)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.exec_driver_sql(
                    "SET TRANSACTION READ WRITE" if apply
                    else "SET TRANSACTION READ ONLY"
                )
                conn.exec_driver_sql("SET LOCAL statement_timeout='12000ms'")
                conn.exec_driver_sql("SET LOCAL lock_timeout='500ms'")
                identity, u, b, state = _qualified(conn)
                if hosted and identity != (DB, ACTOR, ACTOR):
                    raise RuntimeError("HOLD_WRONG_HOSTED_DATABASE_OR_ROLE")
                if not hosted and (
                    engine.url.host not in ("127.0.0.1", "localhost")
                    or engine.url.database != "swes_r2_wnd_bootstrap_disposable"
                ):
                    raise RuntimeError("HOLD_WRONG_DISPOSABLE_DATABASE")
                result = {
                    "task": "WND-02/03/04 phase1", "mode": "apply" if apply else "dry_run",
                    "before": state, "target_item_meta": FOOD_META,
                    "new_binding_scope": "location",
                    "service_mode": "takeaway",
                    "payment_calls": 0, "service_credentials": 0,
                }
                if apply:
                    updated = conn.execute(text("""
                        UPDATE public.atomic_units
                        SET meta=CAST(:meta AS jsonb),row_version=row_version+1,
                            updated_at=now()
                        WHERE id=:id AND tenant_id=:t AND row_version=:version
                          AND meta=CAST(:before AS jsonb)
                        RETURNING row_version,meta
                    """), {
                        "id": u["id"], "t": T, "version": u["row_version"],
                        "meta": json.dumps(FOOD_META,sort_keys=True),
                        "before": json.dumps(PREVIOUS,sort_keys=True),
                    }).mappings().all()
                    if len(updated) != 1 or updated[0]["meta"] != FOOD_META:
                        raise RuntimeError("HOLD_STOCK_POLICY_CAS_FAILURE")
                    changed = conn.execute(text("""
                        UPDATE public.restaurant_customer_catalog_read_bindings
                        SET scope_type='location',scope_id=location_id
                        WHERE id=:id AND tenant_id=:t AND row_version=:version
                          AND scope_type='tenant' AND scope_id IS NULL
                        RETURNING row_version,scope_type,scope_id
                    """), {
                        "id": b["id"], "t": T, "version": b["row_version"],
                    }).mappings().all()
                    if len(changed) != 1 or changed[0]["row_version"] != b["row_version"]+1:
                        raise RuntimeError("HOLD_BINDING_CAS_FAILURE")
                    if changed[0]["scope_id"] != b["location_id"]:
                        raise RuntimeError("HOLD_WRONG_LOCATION_SCOPE")
                    mode = conn.execute(text("""
                        INSERT INTO public.r1_restaurant_service_modes(
                            tenant_id,mode_code,display_name,
                            requires_session,requires_resource,supports_tabs,
                            supports_reservations,allows_remote_origin,
                            active,metadata
                        ) VALUES(
                            :t,'takeaway','SWES TEST Remote Takeaway',
                            false,false,false,false,true,true,
                            CAST(:meta AS jsonb)
                        ) RETURNING id,mode_code,allows_remote_origin
                    """), {
                        "t": T, "meta": json.dumps(TAKEAWAY_META,sort_keys=True),
                    }).mappings().all()
                    if len(mode) != 1 or mode[0]["allows_remote_origin"] is not True:
                        raise RuntimeError("HOLD_TAKEAWAY_MODE_CREATION")
                    result["after"] = {
                        "unit_row_version": updated[0]["row_version"],
                        "binding_row_version": changed[0]["row_version"],
                        "binding_scope": changed[0]["scope_type"],
                        "binding_scope_id": changed[0]["scope_id"],
                        "mode": mode[0]["mode_code"],
                    }
                    result["applied"] = True
                else:
                    result["database_writes"] = False
            return result
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hosted", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("HOLD_DATABASE_URL")
    print(json.dumps(
        execute(url, apply=args.apply, hosted=args.hosted),
        indent=2, default=str, sort_keys=True,
    ))


if __name__ == "__main__":
    main()
