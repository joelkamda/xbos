#!/usr/bin/env python3
"""Verify and optionally accept SO2 operational Party relationships."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import validate_pc0
from core.platform.neutral_proof.dependency_authority import verify_dependency_authority
from scripts.verify_so0_shared_operations import verify_so0
from scripts.verify_so1_atomic_catalog_pricing import static_verify as verify_so1
from scripts.verify_xa_frontend_experience_architecture import verify_xa

SOURCE = "733e226b7468cc1b8a5629a3944ac67a7ab88035"
PREVIOUS = "so1_atomic_catalog_offer_pricing_026"
HEAD = "so2_operational_party_relationships_027"
TEST_DB = "xbos_shared_operations_so2_test"
CONTRACTS = ROOT / "contracts/shared_operations/v1"
LOCAL = {"localhost", "127.0.0.1", "::1"}
PREDECESSOR_TABLES = {"tenants", "parties", "persons", "organization_parties", "party_contacts", "party_roles", "party_relationships", "classification_assignments"}
SO2_TABLES = {"so2_operational_relationships", "so2_relationship_history", "so2_relationship_compatibility_mappings", "so2_relationship_commands"}
FINANCE_TABLES = ("financial_events", "journal_entries", "journal_lines", "financial_obligations", "payment_settlements", "outbox_messages", "reconciliation_controls")


def _json(name: str):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _canonical(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _set_alembic_url(config, rendered_url: str) -> None:
    config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))


def _run_alembic(operation, config, rendered_url: str, target: str) -> None:
    previous = {name: os.environ.get(name) for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
    _set_alembic_url(config, rendered_url)
    os.environ["DATABASE_URL"] = rendered_url
    os.environ["MIGRATION_DATABASE_URL"] = rendered_url
    try:
        operation(config, target)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _development_action(actual_head: str) -> str:
    if actual_head == PREVIOUS:
        return "UPGRADE"
    if actual_head == HEAD:
        return "VERIFY_IN_PLACE"
    raise RuntimeError(f"SO2_DEVELOPMENT_HEAD_UNSAFE={actual_head}")


def _focused_test_paths(root: Path = ROOT) -> tuple[str, ...]:
    gate = (root / "XBOS_SO2_RUN_ACCEPTANCE.cmd").read_text(encoding="utf-8")
    paths = tuple(
        match.replace("\\", "/")
        for match in re.findall(r"tests\\contracts\\[^\s]+\.py", gate)
    )
    if not paths or len(paths) != len(set(paths)):
        raise RuntimeError("SO2_FOCUSED_TEST_PATHS_INVALID")
    missing = tuple(path for path in paths if not (root / path).is_file())
    if missing:
        raise RuntimeError(f"SO2_FOCUSED_TEST_PATH_MISSING={missing}")
    return paths


def _verify_schema(connection, expected_head: str, required_tables: set[str]) -> None:
    actual = connection.exec_driver_sql("SELECT version_num FROM public.alembic_version").scalar_one_or_none()
    if actual != expected_head:
        raise RuntimeError(f"SO2_REPLAY_HEAD_MISMATCH={actual}")
    tables = set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    missing = sorted(required_tables - tables)
    if missing:
        raise RuntimeError(f"SO2_REPLAY_TABLES_MISSING={missing}")


def _snapshot(connection) -> dict[str, dict[str, int]]:
    tables = set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    def counts(names):
        return {name: connection.exec_driver_sql(f'SELECT count(*) FROM public."{name}"').scalar_one() for name in sorted(set(names) & tables)}
    return {"finance": counts(FINANCE_TABLES), "party": counts({"parties", "persons", "organization_parties", "party_contacts", "party_roles", "party_relationships"}), "so2": counts(SO2_TABLES)}


def _verify_snapshot(action: str, before: dict, after: dict) -> None:
    if before["finance"] != after["finance"]:
        raise RuntimeError("SO2_DEVELOPMENT_FINANCE_CHANGED")
    if before["party"] != after["party"]:
        raise RuntimeError("SO2_DEVELOPMENT_PARTY_CHANGED")
    if action == "VERIFY_IN_PLACE" and before["so2"] != after["so2"]:
        raise RuntimeError("SO2_DEVELOPMENT_REPEAT_MUTATED_DATA")
    if action == "UPGRADE" and any(after["so2"].values()):
        raise RuntimeError("SO2_DEVELOPMENT_UPGRADE_SEEDED_DATA")


def static_verify() -> dict[str, object]:
    _focused_test_paths()
    authority = _json("so2_authority.json")
    adoption = _json("so2_legacy_adoption_manifest.json")
    interfaces = _json("so2_public_interfaces.json")
    xa = _json("so2_xa_metadata.json")
    if (authority["source_checkpoint"], authority["previous_head"], authority["accepted_head"]) != (SOURCE, PREVIOUS, HEAD):
        raise RuntimeError("SO2_RELEASE_BOUNDARY")
    if authority["financial_side_effects"] != "NONE" or authority["production_dependency_changes"] != "NONE":
        raise RuntimeError("SO2_FINANCE_OR_DEPENDENCY_BOUNDARY")
    decisions = {item["artifact"]: item for item in adoption["decisions"]}
    if decisions["parties / persons / organization_parties"]["classification"] != "ADOPT" or decisions["financial_counterparties.party_id and debtor/creditor Party UUIDs"]["classification"] != "PRESERVE":
        raise RuntimeError("SO2_LEGACY_ADOPTION")
    if interfaces["party_authority"]["owner"] != "PC2" or interfaces["authorization"]["owner"] != "PC5" or interfaces["semantic_authority"]["owner"] != "PC3":
        raise RuntimeError("SO2_PLATFORM_BOUNDARY")
    if xa["xa_contract"] != "xa.frontend-experience.v1" or xa["frontend_implementation"] != "NONE":
        raise RuntimeError("SO2_XA_BOUNDARY")
    up = (ROOT / "alembic_neutral/sql/so2_operational_party_relationships_up.sql").read_text(encoding="utf-8")
    required = ("CREATE TABLE public.so2_operational_relationships", "REFERENCES public.parties(tenant_id,id)", "CREATE TABLE public.so2_relationship_history", "CREATE TABLE public.so2_relationship_compatibility_mappings")
    if not all(marker in up for marker in required):
        raise RuntimeError("SO2_MIGRATION_COVERAGE")
    forbidden = ("CREATE TABLE public.customers", "CREATE TABLE public.suppliers", "INSERT INTO public.financial_", "UPDATE public.financial_", "DROP TABLE public.parties", "TRUNCATE")
    if any(marker in up for marker in forbidden):
        raise RuntimeError("SO2_DUPLICATE_IDENTITY_OR_FINANCE_SQL")
    profiles = [_json("examples/retail_service_crm_profile.json"), _json("examples/professional_service_crm_profile.json")]
    if profiles[0]["terminology"] == profiles[1]["terminology"] or profiles[0]["relationship_types"] == profiles[1]["relationship_types"]:
        raise RuntimeError("SO2_NEUTRALITY_PROFILES")
    active_roots = (ROOT / "shared_operations/so2", CONTRACTS / "so2_authority.json", CONTRACTS / "so2_public_interfaces.json")
    forbidden_literals = (bytes((87, 78, 68)), b"Wine & Dine", b"Logpom", b"restaurant")
    for base in active_roots:
        paths = base.rglob("*") if base.is_dir() else (base,)
        for path in paths:
            if path.is_file() and any(token.lower() in path.read_bytes().lower() for token in forbidden_literals):
                raise RuntimeError(f"SO2_INDUSTRY_DEFAULT={path.relative_to(ROOT)}")
    dependency = verify_dependency_authority(ROOT, json.loads((ROOT / "contracts/platform/v1/pc6_dependency_authority.json").read_text()))
    if dependency["pin_count"] != 14 or dependency["python"] != "3.13.3":
        raise RuntimeError("SO2_DEPENDENCY_AUTHORITY")
    if validate_pc0(ROOT)["status"] != "PASS" or verify_xa()["status"] != "PASS" or verify_so0()["status"] != "PASS" or verify_so1()["status"] != "PASS":
        raise RuntimeError("SO2_FROZEN_PREDECESSOR")
    manifest = _json("so2_release_manifest.json")
    install_lines = (ROOT / "SO2_INSTALL_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
    inventory = install_lines[install_lines.index("SO2_INSTALL_MANIFEST.txt"):]
    expected = [item["path"] for item in manifest["artifacts"]] + ["contracts/shared_operations/v1/so2_release_manifest.json"]
    if len(inventory) != len(set(inventory)) or set(inventory) != set(expected):
        raise RuntimeError("SO2_PACKAGE_INVENTORY_MISMATCH")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical(path) != item["sha256"]:
            raise RuntimeError(f"SO2_RELEASE_MISMATCH={item['path']}")
    return {"status":"PASS", "source_checkpoint":SOURCE[:7], "previous_head":PREVIOUS, "accepted_head":HEAD, "party_authority":"PC2_REUSED", "identity_separation":"PASS", "neutral_profiles":2, "xa":"PASS", "finance":"UNCHANGED", "dependency_changes":"NONE", "release_artifacts":len(manifest["artifacts"])}


@contextmanager
def _session(engine):
    from sqlalchemy.orm import Session
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            yield session


def database_acceptance() -> dict[str, str]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from core.platform.party import CreatePerson, PartyAuthority, SQLPartyRepository
    from database import engine as application_engine
    from shared_operations.so2 import EstablishRelationship, RelationshipStatus, SO2Authority, SO2AuthorityError
    from shared_operations.so2.sql_repository import SQLSO2Repository

    url = make_url(application_engine.url)
    if url.host not in LOCAL or url.database != "xbos_track_b_dev":
        raise RuntimeError("SO2_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    with application_engine.connect() as connection:
        action = _development_action(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    def selected(name, auto=False):
        return create_engine(url.set(database=name), pool_pre_ping=True, **({"isolation_level":"AUTOCOMMIT"} if auto else {}))
    admin = selected("postgres", True)
    test = None
    success = False
    def drop():
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name":TEST_DB})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DB}" TEMPLATE template0')
        test = selected(TEST_DB)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        test_url = url.set(database=TEST_DB).render_as_string(hide_password=False)
        _run_alembic(command.upgrade, cfg, test_url, PREVIOUS)
        with test.connect() as connection:
            _verify_schema(connection, PREVIOUS, PREDECESSOR_TABLES)
        with test.begin() as connection:
            tenant_a = connection.execute(text("INSERT INTO tenants(code,name,country_code,currency,locale,timezone) VALUES('SO2A','Northstar Services','CA','CAD','en-CA','America/Toronto') RETURNING id")).scalar_one()
            tenant_b = connection.execute(text("INSERT INTO tenants(code,name,country_code,currency,locale,timezone) VALUES('SO2B','Summit Advisory','GB','GBP','en-GB','Europe/London') RETURNING id")).scalar_one()
            finance_before = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCE_TABLES}
        with _session(test) as session:
            party_authority = PartyAuthority(SQLPartyRepository(session))
            party_a = party_authority.create_person(CreatePerson("so2:party:a", tenant_a, "shared-entity-a", "Alex", "Morgan"))
            party_b = party_authority.create_person(CreatePerson("so2:party:b", tenant_b, "shared-entity-b", "Alex", "Morgan"))
        _run_alembic(command.upgrade, cfg, test_url, HEAD)
        with test.connect() as connection:
            _verify_schema(connection, HEAD, PREDECESSOR_TABLES | SO2_TABLES)
        now = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
        with _session(test) as session:
            resolver = lambda tenant, public_id: (lambda row: SimpleNamespace(id=row.id, tenant_id=row.tenant_id, public_id=UUID(str(row.public_id))) if row else None)(session.execute(text("SELECT id,tenant_id,public_id FROM parties WHERE tenant_id=:tenant AND public_id=:public_id"), {"tenant":tenant, "public_id":str(public_id)}).first())
            authority = SO2Authority(SQLSO2Repository(session), party_resolver=resolver, authorize=lambda *args: True, validate_scope=lambda tenant, scope, scope_id: True, semantic_assigner=lambda payload: payload, public_id_factory=lambda: UUID(int=session.execute(text("SELECT nextval('so2_operational_relationships_id_seq')")).scalar_one()+10000))
            customer = authority.establish(EstablishRelationship("so2:customer", tenant_a, party_a.party.public_id, "customer", RelationshipStatus.ACTIVE, now))
            supplier = authority.establish(EstablishRelationship("so2:supplier", tenant_a, party_a.party.public_id, "supplier", RelationshipStatus.ACTIVE, now))
            if customer.party_public_id != supplier.party_public_id or customer.public_id == supplier.public_id:
                raise RuntimeError("SO2_MULTI_RELATIONSHIP_PARTY_FAILED")
            authority.establish(EstablishRelationship("so2:client", tenant_b, party_b.party.public_id, "client", RelationshipStatus.ACTIVE, now))
            try:
                authority.relationship(tenant_b, customer.public_id)
            except SO2AuthorityError:
                pass
            else:
                raise RuntimeError("SO2_CROSS_TENANT_RELATIONSHIP_RESOLVED")
            finance_after = {table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCE_TABLES}
            if finance_after != finance_before:
                raise RuntimeError("SO2_FINANCIAL_EFFECTS_CHANGED")
        _run_alembic(command.downgrade, cfg, test_url, PREVIOUS)
        with test.connect() as connection:
            _verify_schema(connection, PREVIOUS, PREDECESSOR_TABLES)
            if connection.execute(text("SELECT count(*) FROM parties WHERE tenant_id IN (:a,:b)"), {"a":tenant_a, "b":tenant_b}).scalar_one() != 2:
                raise RuntimeError("SO2_DOWNGRADE_CHANGED_PARTY")
        _run_alembic(command.upgrade, cfg, test_url, HEAD)
        with application_engine.connect() as connection:
            before = _snapshot(connection)
        if action == "UPGRADE":
            dev_cfg = Config(str(ROOT / "alembic_neutral.ini"))
            _run_alembic(command.upgrade, dev_cfg, url.render_as_string(hide_password=False), HEAD)
        with application_engine.connect() as connection:
            _verify_schema(connection, HEAD, SO2_TABLES)
            after = _snapshot(connection)
        _verify_snapshot(action, before, after)
        success = True
        return {"clean_replay":"PASS", "upgrade":"PASS", "downgrade_reupgrade":"PASS", "party_reuse":"PASS", "multi_relationship":"PASS", "multi_tenant_explicit_parties":"PASS", "tenant_isolation":"PASS", "development_adoption":action, "financial_effects":"UNCHANGED", "cleanup":"PASS"}
    finally:
        if test:
            test.dispose()
        if success:
            drop()
        admin.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()
    try:
        result = static_verify()
        if args.acceptance:
            result["database"] = database_acceptance()
    except Exception as exc:
        print(f"SO2_VERIFY=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("SO2_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
