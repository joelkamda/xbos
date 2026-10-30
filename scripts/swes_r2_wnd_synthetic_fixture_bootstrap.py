"""PCR V17 SWES R2: one bounded, reversible WND Austin TEST-only fixture.

Does not issue checkout credentials, activate providers, seed payments or grant
roles. Operator owner attestations are mandatory for hosted --apply. Default
--dry-run is a read-only transaction. Exact source-defined table graph.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, text

TENANT = 910001
TENANT_CODE = "SWES_WND_AUSTIN_TEST"
BRANCH_CODE = "SWES-AUSTIN-TEST"
ORG_CODE = "swes-wnd-austin"
LOCATION_CODE = "swes-wnd-austin-virtual"
CATALOG_CODE = "SWES-WND-AUSTIN"
SKU = "SWES-R2-CATALOG-ITEM"
PRICE_CODE = "swes-retail"
EXPECTED_DB = "wnd_xafpay_demo_austin_db"
EXPECTED_ROLE = "wnd_xafpay_demo_austin_db_user"
ROOT = "xafpay:swes:r2:wnd-austin:"
KEYS = ["org", "location", "merchant", "unit", "catalog", "entry", "price", "catalog_binding"]
IDS = {key: uuid5(NAMESPACE_URL, ROOT + key) for key in KEYS}
TABLES = {
    "tenants": "id",
    "branches": "tenant_id",
    "organization_units": "tenant_id",
    "locations": "tenant_id",
    "legacy_branch_structural_mappings": "tenant_id",
    "pa_merchants": "tenant_id",
    "atomic_units": "tenant_id",
    "so1_catalogs": "tenant_id",
    "so1_catalog_entries": "tenant_id",
    "so1_prices": "tenant_id",
    "restaurant_customer_catalog_read_bindings": "tenant_id",
    "r1_restaurant_orders": "tenant_id",
    "service_identities": "tenant_id",
    "scoped_role_assignments": "tenant_id",
}
INSERTS = [
    ("tenant", ("INSERT INTO public.tenants(id,code,name,country_code,currency,locale,timezone,settings,extra_metadata) "
     "VALUES(:tenant,:tenant_code,'WND Austin SWES TEST Only','CM','XAF','en-CM','Africa/Douala',"
     "CAST(:marker AS jsonb),CAST(:marker AS jsonb))")),
    ("branch", ("INSERT INTO public.branches(tenant_id,branch_code,name,city,address,is_active) "
     "VALUES(:tenant,:branch_code,'WND Austin TEST Branch','Synthetic Demo','TEST only',true) "
     "RETURNING id")),
    ("organization", ("INSERT INTO public.organization_units(tenant_id,public_id,unit_type,code,name,timezone_name,active) "
     "VALUES(:tenant,:org_uuid,'branch',:org_code,'WND Austin TEST Organization','Africa/Douala',true) RETURNING id")),
    ("location", ("INSERT INTO public.locations(tenant_id,public_id,code,name,location_kind,timezone_name,address,active) "
     "VALUES(:tenant,:location_uuid,:location_code,'WND Austin TEST Virtual Location','virtual',"
     "'Africa/Douala',CAST(:marker AS jsonb),true) RETURNING id")),
    ("legacy_branch_mapping", ("INSERT INTO public.legacy_branch_structural_mappings("
     "tenant_id,branch_id,organization_unit_id,location_id) "
     "VALUES(:tenant,:branch_id,:organization_id,:location_id)")),
    ("pa_merchant", ("INSERT INTO public.pa_merchants("
     "public_id,tenant_id,administration_state,external_reference) "
     "VALUES(:merchant_uuid,:tenant,'registered','SWES-R2-WND-AUSTIN-TEST-ONLY')")),
    ("atomic_unit", ("INSERT INTO public.atomic_units("
     "public_id,tenant_id,name,sku,unit_type,unit_price,is_active,meta) "
     "VALUES(:unit_uuid,:tenant,'SWES Synthetic Menu Item',:sku,'product',NULL,true,CAST(:marker AS jsonb)) RETURNING id")),
    ("catalog", ("INSERT INTO public.so1_catalogs("
     "public_id,tenant_id,code,name,scope_type,scope_id,effective_from,active) "
     "VALUES(:catalog_uuid,:tenant,:catalog_code,'SWES Synthetic Catalog','tenant',NULL,:effective,true) RETURNING id")),
    ("catalog_entry", ("INSERT INTO public.so1_catalog_entries("
     "public_id,tenant_id,catalog_id,target_type,atomic_unit_id,offer_id,semantic_reference,enabled,effective_from) "
     "VALUES(:entry_uuid,:tenant,:catalog_id,'atomic_unit',:unit_id,NULL,'swes-test-menu-item',true,:effective)")),
    ("price", ("INSERT INTO public.so1_prices("
     "public_id,tenant_id,target_type,atomic_unit_id,offer_id,price_code,amount,currency,"
     "scope_type,scope_id,effective_from,active) "
     "VALUES(:price_uuid,:tenant,'atomic_unit',:unit_id,NULL,:price_code,1000,'XAF',"
     "'tenant',NULL,:effective,true)")),
    ("catalog_binding", ("INSERT INTO public.restaurant_customer_catalog_read_bindings("
     "public_id,tenant_id,merchant_public_id,location_id,catalog_public_id,price_code,"
     "currency,scope_type,scope_id,effective_from,active) "
     "VALUES(:catalog_binding_uuid,:tenant,:merchant_uuid,:location_id,:catalog_uuid,:price_code,"
     "'XAF','tenant',NULL,:effective,true)")),
]


def _parameters():
    params = {
        "tenant": TENANT,
        "tenant_code": TENANT_CODE,
        "branch_code": BRANCH_CODE,
        "org_code": ORG_CODE,
        "location_code": LOCATION_CODE,
        "catalog_code": CATALOG_CODE,
        "sku": SKU,
        "price_code": PRICE_CODE,
        "effective": datetime.now(timezone.utc) - timedelta(minutes=2),
        "marker": json.dumps({"test_only": True, "campaign": "PCR_V17_SWES_R2"}),
    }
    params.update({key + "_uuid": str(value) for key, value in IDS.items()})
    return params


def _counts(conn):
    result = {}
    for table, column in TABLES.items():
        # All table and column identifiers above are fixed code-owned constants.
        result[table] = int(conn.execute(
            text(f"SELECT count(*) FROM public.{table} WHERE {column}=:tenant"),
            {"tenant": TENANT},
        ).scalar_one())
    return result


def _identity(conn, *, hosted):
    data = conn.execute(text(
        "SELECT current_database(), current_user, session_user"
    )).one()
    if hosted and tuple(data) != (EXPECTED_DB, EXPECTED_ROLE, EXPECTED_ROLE):
        raise RuntimeError("SWES_HOLD_UNEXPECTED_HOSTED_DATABASE_ROLE")
    if not hosted:
        if conn.engine.url.host not in ("127.0.0.1", "localhost"):
            raise RuntimeError("SWES_HOLD_NONLOCAL_TEST_DATABASE")
        if conn.engine.url.database != "swes_r2_wnd_bootstrap_disposable":
            raise RuntimeError("SWES_HOLD_WRONG_LOCAL_TEST_DATABASE")
    return {"database": data[0], "current_user": data[1]}


def execute(url: str, mode: str, *, hosted: bool):
    if mode == "apply" and hosted and os.environ.get(
        "SWES_WND_OWNER_ATTESTED_SYNTHETIC_ONLY"
    ) != "I_CONFIRM_TEST_ONLY":
        raise RuntimeError("SWES_HOLD_OWNER_TEST_ONLY_ATTESTATION_REQUIRED")
    engine = create_engine(url, pool_pre_ping=False)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY" if mode == "dry-run"
                                     else "SET TRANSACTION READ WRITE")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '15000ms'")
                conn.exec_driver_sql("SET LOCAL lock_timeout = '1000ms'")
                identity = _identity(conn, hosted=hosted)
                before = _counts(conn)
                if mode == "dry-run":
                    output = {"mode": mode, "identity": identity, "before": before,
                              "no_writes": True, "test_only": True}
                elif mode == "apply":
                    if any(before.values()):
                        raise RuntimeError("SWES_HOLD_CANDIDATE_TENANT_NOT_EMPTY")
                    p = _parameters()
                    for name, statement in INSERTS:
                        result = conn.execute(text(statement), p)
                        if name == "branch":
                            p["branch_id"] = int(result.scalar_one())
                        elif name == "organization":
                            p["organization_id"] = int(result.scalar_one())
                        elif name == "location":
                            p["location_id"] = int(result.scalar_one())
                        elif name == "atomic_unit":
                            p["unit_id"] = int(result.scalar_one())
                        elif name == "catalog":
                            p["catalog_id"] = int(result.scalar_one())
                    after = _counts(conn)
                    expected = {key: 1 for key in TABLES}
                    expected["r1_restaurant_orders"] = 0
                    expected["service_identities"] = 0
                    expected["scoped_role_assignments"] = 0
                    if after != expected:
                        raise RuntimeError("SWES_HOLD_UNEXPECTED_FIXTURE_COUNTS")
                    output = {"mode": mode, "identity": identity, "before": before,
                              "after": after, "tenant_id": TENANT,
                              "merchant_state": "registered",
                              "price": {"currency": "XAF", "amount": 1000},
                              "checkout_service_identity_issued": False,
                              "provider_calls": 0}
                else:
                    raise RuntimeError("SWES_UNRECOGNIZED_MODE")
            return output
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hosted", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("SWES_HOLD_MISSING_DATABASE_URL")
    mode = "apply" if args.apply else "dry-run"
    result = execute(url, mode, hosted=args.hosted)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
