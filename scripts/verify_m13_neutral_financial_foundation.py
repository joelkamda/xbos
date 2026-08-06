"""Guarded M1.3 fresh-build and source-state adoption rehearsal.

Only two fixed local PostgreSQL database names are permitted. Successful runs
drop both disposable databases. Failed runs retain the failing database for
inspection and print an explicit cleanup command.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.persistence.m13_foundation import (
    ADOPTION_REHEARSAL_DATABASE,
    ALLOWED_REHEARSAL_DATABASES,
    FOUNDATION_REVISION,
    FOUNDATION_TABLES,
    FRESH_REHEARSAL_DATABASE,
    SOURCE_AUTHORITY_REVISION,
    SOURCE_STATE_REVISION,
    checked_rehearsal_url,
)


ALEMBIC_CONFIG = ROOT / "alembic_neutral.ini"


def _base_url():
    from database import DATABASE_URL

    return make_url(DATABASE_URL)


def _admin_engine():
    url = _base_url().set(database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def _exists(database_name: str) -> bool:
    with _admin_engine().connect() as connection:
        return bool(
            connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar()
        )


def _create(database_name: str) -> None:
    checked_rehearsal_url(_base_url(), database_name)
    if _exists(database_name):
        raise RuntimeError(
            f"Disposable database already exists: {database_name}. "
            "Inspect it or drop it with this script before retrying."
        )
    with _admin_engine().connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')


def _drop(database_name: str) -> None:
    checked_rehearsal_url(_base_url(), database_name)
    with _admin_engine().connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": database_name},
        )
        connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')


def _url(database_name: str):
    return checked_rehearsal_url(_base_url(), database_name)


def _alembic_config(database_name: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG))
    config.set_main_option(
        "sqlalchemy.url",
        _url(database_name).render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _with_database_url(database_name: str):
    class DatabaseUrlContext:
        def __enter__(self):
            self.previous = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = _url(database_name).render_as_string(
                hide_password=False
            )

        def __exit__(self, exc_type, exc, traceback):
            if self.previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = self.previous

    return DatabaseUrlContext()


def _upgrade(database_name: str, revision: str = "head") -> None:
    with _with_database_url(database_name):
        command.upgrade(_alembic_config(database_name), revision)


def _downgrade(database_name: str, revision: str) -> None:
    with _with_database_url(database_name):
        command.downgrade(_alembic_config(database_name), revision)


def _stamp_source_state(database_name: str) -> None:
    with _with_database_url(database_name):
        command.stamp(
            _alembic_config(database_name),
            SOURCE_STATE_REVISION,
            purge=True,
        )


def _install_source_state_with_old_authority(database_name: str) -> None:
    with _with_database_url(database_name):
        command.upgrade(_alembic_config(database_name), SOURCE_STATE_REVISION)
    engine = create_engine(_url(database_name), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM public.alembic_version"))
            connection.execute(
                text("INSERT INTO public.alembic_version(version_num) VALUES (:revision)"),
                {"revision": SOURCE_AUTHORITY_REVISION},
            )
    finally:
        engine.dispose()


def _current_revision(connection) -> str:
    return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _verify_schema(database_name: str) -> None:
    engine = create_engine(_url(database_name), poolclass=NullPool)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names(schema="public"))
        missing = set(FOUNDATION_TABLES) - tables
        if missing:
            raise AssertionError(f"Missing M1.3 tables: {sorted(missing)}")

        with engine.connect() as connection:
            if _current_revision(connection) != FOUNDATION_REVISION:
                raise AssertionError("M1.3 database is not at the foundation head")
            for table_name in ("financial_event_type_versions", "financial_events"):
                count = connection.execute(
                    text(f"SELECT count(*) FROM public.{table_name}")
                ).scalar_one()
                if count != 0:
                    raise AssertionError(f"M1 must leave {table_name} empty")
    finally:
        engine.dispose()


def _expect_database_rejection(connection, statement: str, parameters: dict) -> None:
    nested = connection.begin_nested()
    try:
        connection.execute(text(statement), parameters)
    except DBAPIError:
        nested.rollback()
        return
    nested.rollback()
    raise AssertionError("Database accepted an operation that M1.3 must reject")


def _verify_invariants(database_name: str) -> None:
    engine = create_engine(_url(database_name), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO tenants
                            (id, code, name, country_code, currency, locale, timezone)
                        VALUES
                            (900001, 'M13A', 'M1.3 A', 'CM', 'XAF', 'en-CM', 'Africa/Douala'),
                            (900002, 'M13B', 'M1.3 B', 'CM', 'XAF', 'en-CM', 'Africa/Douala')
                        """
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO currency_assets "
                        "(code, asset_kind, display_name, minor_unit_scale) "
                        "VALUES ('XAF','fiat','Central African CFA franc',0)"
                    )
                )
                org_id = connection.execute(
                    text(
                        "INSERT INTO organization_units "
                        "(tenant_id, unit_type, code, name) "
                        "VALUES (900001,'branch','M13-ORG','M1.3 branch') RETURNING id"
                    )
                ).scalar_one()
                source_id = connection.execute(
                    text(
                        "INSERT INTO kernel_source_records "
                        "(tenant_id, organization_unit_id, source_component, aggregate_type, aggregate_external_id) "
                        "VALUES (900001,:org,'contract_test','fixture','m13-1') RETURNING id"
                    ),
                    {"org": org_id},
                ).scalar_one()
                connection.execute(
                    text(
                        """
                        INSERT INTO financial_event_type_versions
                            (event_type_code,event_version,display_name,definition,
                             amount_policy,default_economic_role,reconciliation_effect,
                             effective_from,approved_at,definition_hash)
                        VALUES
                            ('M13_TEST_EVENT',1,'M1.3 test event','Rehearsal only',
                             'positive','control','none',now(),now(),repeat('a',64))
                        """
                    )
                )

                _expect_database_rejection(
                    connection,
                    """
                    INSERT INTO financial_events
                        (tenant_id,organization_unit_id,event_type_code,event_version,
                         amount,currency_code,economic_role,source_record_id,occurred_at,
                         business_date,calendar_policy_version,actor_service,
                         idempotency_scope,idempotency_key,correlation_id)
                    VALUES
                        (900002,:org,'M13_TEST_EVENT',1,1,'XAF','control',:source,
                         now(),current_date,1,'m13-rehearsal','m13','cross-tenant',gen_random_uuid())
                    """,
                    {"org": org_id, "source": source_id},
                )

                event_id = connection.execute(
                    text(
                        """
                        INSERT INTO financial_events
                            (tenant_id,organization_unit_id,event_type_code,event_version,
                             amount,currency_code,economic_role,source_record_id,occurred_at,
                             business_date,calendar_policy_version,actor_service,
                             idempotency_scope,idempotency_key,correlation_id)
                        VALUES
                            (900001,:org,'M13_TEST_EVENT',1,1,'XAF','control',:source,
                             now(),current_date,1,'m13-rehearsal','m13','immutable',gen_random_uuid())
                        RETURNING id
                        """
                    ),
                    {"org": org_id, "source": source_id},
                ).scalar_one()

                _expect_database_rejection(
                    connection,
                    "UPDATE financial_events SET amount = 2 WHERE id = :event_id",
                    {"event_id": event_id},
                )
                _expect_database_rejection(
                    connection,
                    "DELETE FROM financial_events WHERE id = :event_id",
                    {"event_id": event_id},
                )
            finally:
                outer.rollback()
    finally:
        engine.dispose()


def _fresh_rehearsal() -> None:
    name = FRESH_REHEARSAL_DATABASE
    _create(name)
    try:
        _upgrade(name)
        _verify_schema(name)
        _verify_invariants(name)
        _downgrade(name, SOURCE_STATE_REVISION)
        engine = create_engine(_url(name), poolclass=NullPool)
        try:
            remaining = set(inspect(engine).get_table_names()) & set(FOUNDATION_TABLES)
            if remaining:
                raise AssertionError(f"M1.3 downgrade left tables: {sorted(remaining)}")
        finally:
            engine.dispose()
        _upgrade(name)
        _verify_schema(name)
    except Exception:
        print(f"Fresh rehearsal failed; retained database={name}")
        raise
    else:
        _drop(name)
        print(f"fresh_reconstruction=PASS database={name} dropped=true")


def _adoption_rehearsal() -> None:
    name = ADOPTION_REHEARSAL_DATABASE
    _create(name)
    try:
        _install_source_state_with_old_authority(name)
        engine = create_engine(_url(name), poolclass=NullPool)
        try:
            with engine.connect() as connection:
                if _current_revision(connection) != SOURCE_AUTHORITY_REVISION:
                    raise AssertionError("Source authority revision rehearsal is invalid")
                before = set(inspect(connection).get_table_names(schema="public"))
        finally:
            engine.dispose()

        _stamp_source_state(name)
        _upgrade(name)
        _verify_schema(name)
        _verify_invariants(name)

        engine = create_engine(_url(name), poolclass=NullPool)
        try:
            after = set(inspect(engine).get_table_names(schema="public"))
            removed_source_tables = (before - {"alembic_version"}) - after
            if removed_source_tables:
                raise AssertionError(
                    f"Adoption removed source-state tables: {sorted(removed_source_tables)}"
                )
        finally:
            engine.dispose()
    except Exception:
        print(f"Adoption rehearsal failed; retained database={name}")
        raise
    else:
        _drop(name)
        print(f"existing_state_adoption=PASS database={name} dropped=true")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("create-and-verify")
    drop_parser = subparsers.add_parser("drop")
    drop_parser.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()

    if args.command == "status":
        for name in sorted(ALLOWED_REHEARSAL_DATABASES):
            print(f"database={name} exists={str(_exists(name)).lower()}")
        return 0
    if args.command == "drop":
        if args.confirm_database_name not in ALLOWED_REHEARSAL_DATABASES:
            raise RuntimeError("Exact approved disposable database name is required")
        _drop(args.confirm_database_name)
        print(f"dropped={args.confirm_database_name}")
        return 0

    _fresh_rehearsal()
    _adoption_rehearsal()
    print("m13_neutral_financial_foundation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
