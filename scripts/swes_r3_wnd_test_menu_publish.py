"""SWES R3: stage one synthetic R2 menu section for WND Austin TEST-only.

This fixture is only a menu-discoverability bridge. It never transitions the
PA merchant, grants CC checkout permissions, or contacts a payment provider.
Default is read-only preflight. Writes must be a single atomic TEST transaction.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, text

TENANT = 910001
DB = "wnd_xafpay_demo_austin_db"
ACTOR = "wnd_xafpay_demo_austin_db_user"
ROOT = "xafpay:swes:r2:wnd-austin:"
CATALOG = str(uuid5(NAMESPACE_URL, ROOT + "catalog"))
ENTRY = str(uuid5(NAMESPACE_URL, ROOT + "entry"))
SECTION = str(uuid5(NAMESPACE_URL, ROOT + "menu_section"))
CODE = "swes-test-menu"
TABLES = ("r2_restaurant_menu_sections", "r2_restaurant_menu_section_entries")


def _counts(c):
    return {
        table: int(c.execute(
            text(f"SELECT count(*) FROM public.{table} WHERE tenant_id=:t"),
            {"t": TENANT},
        ).scalar_one())
        for table in TABLES
    }


def publish(url: str, *, apply: bool, hosted: bool):
    if apply and hosted and os.environ.get(
        "SWES_WND_OWNER_ATTESTED_SYNTHETIC_ONLY"
    ) != "I_CONFIRM_TEST_ONLY":
        raise RuntimeError("HOLD_TEST_OWNER_ATTESTATION")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.exec_driver_sql(
                    "SET TRANSACTION READ WRITE" if apply
                    else "SET TRANSACTION READ ONLY"
                )
                conn.exec_driver_sql("SET LOCAL statement_timeout='15000ms'")
                conn.exec_driver_sql("SET LOCAL lock_timeout='500ms'")
                ident = tuple(conn.execute(text(
                    "SELECT current_database(),current_user,session_user"
                )).one())
                if hosted:
                    if ident != (DB, ACTOR, ACTOR):
                        raise RuntimeError("HOLD_WRONG_HOSTED_DB_ROLE")
                elif (
                    engine.url.host not in ("127.0.0.1", "localhost")
                    or engine.url.database != "swes_r2_wnd_bootstrap_disposable"
                ):
                    raise RuntimeError("HOLD_WRONG_DISPOSABLE_DB")

                fixture = conn.execute(text("""
                    SELECT count(*)
                    FROM public.so1_catalogs c
                    JOIN public.so1_catalog_entries e
                      ON (e.tenant_id,e.catalog_id)=(c.tenant_id,c.id)
                    JOIN public.restaurant_customer_catalog_read_bindings b
                      ON b.tenant_id=c.tenant_id
                     AND b.catalog_public_id=c.public_id
                    JOIN public.pa_merchants m
                      ON m.tenant_id=c.tenant_id
                     AND m.public_id=b.merchant_public_id
                    WHERE c.tenant_id=:t AND c.public_id=CAST(:catalog AS uuid)
                      AND e.public_id=CAST(:entry AS uuid)
                      AND e.enabled AND c.active AND b.active
                      AND m.administration_state='registered'
                """), {"t": TENANT, "catalog": CATALOG, "entry": ENTRY}).scalar_one()
                if fixture != 1:
                    raise RuntimeError("HOLD_INVALID_TEST_FIXTURE")
                before = _counts(conn)
                out = {
                    "database": ident[0], "tenant": TENANT,
                    "before": before, "source_catalog_entry_verified": True,
                    "merchant_state": "registered",
                    "payment_calls": 0,
                }
                if apply:
                    if before != {name: 0 for name in TABLES}:
                        raise RuntimeError("HOLD_MENU_ALREADY_PRESENT")
                    start = datetime.now(timezone.utc) - timedelta(minutes=2)
                    section_id = int(conn.execute(text("""
                        INSERT INTO public.r2_restaurant_menu_sections(
                            public_id,tenant_id,catalog_id,section_code,
                            display_name,sort_order,effective_from,active,metadata
                        )
                        SELECT CAST(:section AS uuid),:t,c.id,:code,
                               'Synthetic Test Menu',0,:start,true,
                               CAST(:metadata AS jsonb)
                          FROM public.so1_catalogs c
                         WHERE c.tenant_id=:t
                           AND c.public_id=CAST(:catalog AS uuid)
                        RETURNING id
                    """), {
                        "section": SECTION, "t": TENANT, "code": CODE,
                        "start": start, "catalog": CATALOG,
                        "metadata": json.dumps({"synthetic_only": True}),
                    }).scalar_one())
                    conn.execute(text("""
                        INSERT INTO public.r2_restaurant_menu_section_entries(
                            tenant_id,section_id,catalog_entry_public_id,
                            sort_order,effective_from
                        ) VALUES(:t,:section,CAST(:entry AS uuid),0,:start)
                    """), {
                        "t": TENANT, "section": section_id,
                        "entry": ENTRY, "start": start,
                    })
                    after = _counts(conn)
                    if after != {name: 1 for name in TABLES}:
                        raise RuntimeError("HOLD_UNEXPECTED_MENU_COUNTS")
                    out.update({"after": after, "mode": "apply"})
                else:
                    out.update({"mode": "read_only", "database_writes": False})
            return out
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hosted", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("HOLD_MISSING_DATABASE_URL")
    print(json.dumps(publish(url, apply=args.apply, hosted=args.hosted),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
