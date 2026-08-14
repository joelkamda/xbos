#!/usr/bin/env python3
"""Verify the Shared Operations aggregate conformance/freeze and local PostgreSQL hardening."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "0f2fa1b5f7226ad117425f37a808aab9b0c23b32"
PREVIOUS = "so10_scheduling_reservations_service_execution_035"
HEAD = "so_aggregate_conformance_hardening_036"
CONTRACTS = ROOT / "contracts/shared_operations/v1"
TEST_DB = "xbos_shared_operations_aggregate_test"
LOCAL = {"localhost", "127.0.0.1", "::1"}

EXPECTED_COMPONENT_HEADS = {
    "SO0": ("pc5_identity_policy_audit_025", "pc5_identity_policy_audit_025"),
    "SO1": ("pc5_identity_policy_audit_025", "so1_atomic_catalog_offer_pricing_026"),
    "SO2": ("so1_atomic_catalog_offer_pricing_026", "so2_operational_party_relationships_027"),
    "SO3": ("so2_operational_party_relationships_027", "so3_inventory_stock_movement_028"),
    "SO4": ("so3_inventory_stock_movement_028", "so4_procurement_supplier_operations_029"),
    "SO5": ("so4_procurement_supplier_operations_029", "so5_resources_operational_assignment_030"),
    "SO6": ("so5_resources_operational_assignment_030", "so6_workflows_tasks_operational_approvals_031"),
    "SO7": ("so6_workflows_tasks_operational_approvals_031", "so7_documents_files_evidence_search_032"),
    "SO8": ("so7_documents_files_evidence_search_032", "so8_communications_delivery_offline_033"),
    "SO9": ("so8_communications_delivery_offline_033", "so9_reporting_read_models_automation_034"),
    "SO10": ("so9_reporting_read_models_automation_034", PREVIOUS),
}
EXPECTED_OWNERS = {
    "commerce": "SO1",
    "crm_relationships": "SO2",
    "inventory": "SO3",
    "procurement": "SO4",
    "resources": "SO5",
    "workflows": "SO6",
    "documents": "SO7",
    "communications": "SO8",
    "reports": "SO9",
    "scheduling": "SO10",
}
FINANCE_TABLES = (
    "financial_events", "journal_entries", "financial_obligations",
    "payment_settlements", "outbox_messages", "idempotency_records",
)
FINANCE_WRITE_TABLES = (
    "financial_events", "journal_entries", "journal_lines", "financial_obligations",
    "payment_intents", "canonical_payment_attempts", "payment_settlements",
    "financial_value_sources", "outbox_messages", "idempotency_records",
    "operational_accounts", "value_transfers", "reconciliation_windows",
    "reconciliation_controls",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _set_url(config, url: str) -> None:
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def _run(operation, config, url: str, target: str) -> None:
    old = {k: os.environ.get(k) for k in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
    _set_url(config, url)
    os.environ.update(DATABASE_URL=url, MIGRATION_DATABASE_URL=url)
    try:
        operation(config, target)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _component_manifests() -> dict[str, dict]:
    result = {}
    for number in range(0, 11):
        code = f"SO{number}"
        result[code] = _json(CONTRACTS / f"so{number}_release_manifest.json")
    return result


def _verify_component_lineage() -> None:
    manifests = _component_manifests()
    for code, (previous, accepted) in EXPECTED_COMPONENT_HEADS.items():
        item = manifests[code]
        if (item.get("previous_head"), item.get("accepted_head")) != (previous, accepted):
            raise RuntimeError(f"SO_AGG_COMPONENT_LINEAGE={code}")
        if code != "SO0":
            for artifact in item.get("artifacts", []):
                path = ROOT / artifact["path"]
                if not path.is_file() or _canonical(path) != artifact["sha256"]:
                    raise RuntimeError(f"SO_AGG_COMPONENT_RELEASE_MISMATCH={code}:{artifact['path']}")


def _verify_authority_graph() -> None:
    module_map = _json(ROOT / "contracts/platform/v1/pc0_module_map.json")
    modules = {item["code"]: item for item in module_map["modules"]}
    if len(modules) != len(module_map["modules"]):
        raise RuntimeError("SO_AGG_DUPLICATE_MODULE_CODE")
    for code, owner in EXPECTED_OWNERS.items():
        item = modules.get(code)
        if not item or item.get("owner") != owner:
            raise RuntimeError(f"SO_AGG_AUTHORITY_OWNER={code}")
    if modules.get("catalog", {}).get("owner") != "SO0/SO1":
        raise RuntimeError("SO_AGG_CATALOG_COMPATIBILITY_OWNER")
    expected = {
        2: ("financial_side_effects", "NONE"),
        3: ("financial_valuation", "EXCLUDED"),
        4: ("inventory_authority", "SO3_PUBLIC_CONTRACT_REUSED"),
        5: ("security_roles", "PC5_ONLY"),
        6: ("security_approval_boundary", "PC5_ONLY"),
        7: ("search_authority", "SO7_DERIVED_PROJECTION"),
        8: ("financial_outbox_authority", "NEUTRAL_FINANCE_PRESERVED"),
        9: ("read_model_authority", "SO9_DERIVED_REBUILDABLE"),
        10: ("financial_authority", "NEUTRAL_FINANCE_PRESERVED"),
    }
    for number, (key, value) in expected.items():
        authority = _json(CONTRACTS / f"so{number}_authority.json")
        if authority.get(key) != value:
            raise RuntimeError(f"SO_AGG_AUTHORITY_BOUNDARY=SO{number}:{key}")


def _verify_public_boundaries() -> None:
    for number in range(1, 11):
        root = ROOT / f"shared_operations/so{number}"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                target = None
                if isinstance(node, ast.ImportFrom):
                    target = node.module
                elif isinstance(node, ast.Import) and node.names:
                    for alias in node.names:
                        name = alias.name
                        match = re.match(r"shared_operations\.so(\d+)(\..+)?$", name)
                        if match and int(match.group(1)) != number and match.group(2):
                            raise RuntimeError(f"SO_AGG_PRIVATE_IMPORT={path.relative_to(ROOT)}:{name}")
                    continue
                if target:
                    match = re.match(r"shared_operations\.so(\d+)(\..+)?$", target)
                    if match and int(match.group(1)) != number and match.group(2):
                        raise RuntimeError(f"SO_AGG_PRIVATE_IMPORT={path.relative_to(ROOT)}:{target}")

        # Persistence may hold tenant-qualified FKs/read references, but must never
        # mutate another SO or Finance authority.
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:public\.)?([A-Za-z0-9_]+)", source, re.I):
                table = match.group(2).lower()
                other = re.match(r"so(\d+)_", table)
                if other and int(other.group(1)) != number:
                    raise RuntimeError(f"SO_AGG_EXTERNAL_SO_WRITE=SO{number}:{table}")
                if table in FINANCE_WRITE_TABLES:
                    raise RuntimeError(f"SO_AGG_FINANCE_WRITE=SO{number}:{table}")


def _verify_tenant_idempotency() -> None:
    hardening = (ROOT / "alembic_neutral/sql/so_aggregate_conformance_hardening_up.sql").read_text(encoding="utf-8")
    repository = (ROOT / "shared_operations/so2/sql_repository.py").read_text(encoding="utf-8")
    for marker in (
        "ADD COLUMN tenant_id INTEGER NULL",
        "UNIQUE(tenant_id,command_key)",
        "FOREIGN KEY(tenant_id,result_id)",
        "SO_AGG_SO2_COMMAND_TENANT_BACKFILL_REQUIRED",
    ):
        if marker not in hardening:
            raise RuntimeError(f"SO_AGG_SO2_TENANT_HARDENING={marker}")
    for marker in ("ON CONFLICT(tenant_id,command_key)", "WHERE tenant_id=:tenant AND command_key=:key"):
        if marker not in repository:
            raise RuntimeError(f"SO_AGG_SO2_REPOSITORY_SCOPE={marker}")
    for number in range(3, 11):
        candidates = list((ROOT / "alembic_neutral/sql").glob(f"so{number}_*_up.sql"))
        source = "\n".join(path.read_text(encoding="utf-8") for path in candidates)
        if "command" in source.lower() and "UNIQUE(tenant_id,command_key)" not in source:
            raise RuntimeError(f"SO_AGG_COMMAND_SCOPE=SO{number}")


def _verify_neutrality_and_pk_readiness() -> None:
    forbidden = (b"wine & dine", b"logpom", b"restaurant", bytes((87, 78, 68)).lower())
    for path in (ROOT / "shared_operations").rglob("*.py"):
        data = path.read_bytes().lower()
        if any(token in data for token in forbidden):
            raise RuntimeError(f"SO_AGG_INDUSTRY_DEFAULT={path.relative_to(ROOT)}")
    for number in range(1, 11):
        required = (
            CONTRACTS / f"so{number}_authority.json",
            CONTRACTS / f"so{number}_public_interfaces.json",
            CONTRACTS / f"so{number}_xa_metadata.json",
        )
        if not all(path.is_file() for path in required):
            raise RuntimeError(f"SO_AGG_PK_DECLARATION=SO{number}")
        manifest = _json(CONTRACTS / f"so{number}_release_manifest.json")
        examples = [a for a in manifest.get("artifacts", []) if "/examples/" in a["path"]]
        if len(examples) < 2:
            raise RuntimeError(f"SO_AGG_NEUTRAL_PROFILE_COUNT=SO{number}")


def static_verify() -> dict[str, object]:
    from core.platform.architecture_contract import validate_pc0
    from scripts.verify_pc6_neutral_platform import verify_dependency_authority

    contract = _json(CONTRACTS / "so_aggregate_conformance_freeze.json")
    if (contract.get("source_checkpoint"), contract.get("previous_head"), contract.get("accepted_head")) != (SOURCE, PREVIOUS, HEAD):
        raise RuntimeError("SO_AGG_RELEASE_BOUNDARY")
    if contract.get("business_capability_change") != "NONE" or contract.get("migration") != "CONFORMANCE_HARDENING_ONLY":
        raise RuntimeError("SO_AGG_SCOPE")
    if contract["aggregate_invariants"]["finance"] != "UNCHANGED" or contract["aggregate_invariants"]["dependencies"] != "UNCHANGED":
        raise RuntimeError("SO_AGG_FINANCE_DEPENDENCY_BOUNDARY")

    report = validate_pc0(ROOT)
    if report["status"] != "PASS":
        raise RuntimeError("SO_AGG_PC0")
    dependency = verify_dependency_authority(
        ROOT, _json(ROOT / "contracts/platform/v1/pc6_dependency_authority.json")
    )
    if dependency["python"] != "3.13.3" or dependency["pin_count"] != 14:
        raise RuntimeError("SO_AGG_DEPENDENCY_AUTHORITY")

    _verify_component_lineage()
    _verify_authority_graph()
    _verify_public_boundaries()
    _verify_tenant_idempotency()
    _verify_neutrality_and_pk_readiness()

    manifest = _json(CONTRACTS / "so_aggregate_release_manifest.json")
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if not path.is_file() or _canonical(path) != artifact["sha256"]:
            raise RuntimeError(f"SO_AGG_RELEASE_MISMATCH={artifact['path']}")
    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": PREVIOUS,
        "accepted_head": HEAD,
        "components": 11,
        "authority_graph": "PASS",
        "public_boundaries": "PASS",
        "tenant_isolation": "PASS",
        "neutrality": "PASS",
        "migration_lineage": "PASS",
        "xa_conformance": "PASS",
        "finance": "UNCHANGED",
        "dependencies": "UNCHANGED",
        "release_integrity": "PASS",
        "pk_readiness": "PASS",
        "hardening": "SO2_TENANT_SCOPED_IDEMPOTENCY",
        "release_artifacts": len(manifest["artifacts"]),
    }


def _development_action(version: str) -> str:
    if version == PREVIOUS:
        return "UPGRADE"
    if version == HEAD:
        return "VERIFY_IN_PLACE"
    raise RuntimeError(f"SO_AGG_DEVELOPMENT_HEAD_UNSAFE={version}")


def _counts(connection) -> dict[str, int]:
    names = [row[0] for row in connection.execute(
        __import__("sqlalchemy").text(
            """SELECT tablename FROM pg_tables
               WHERE schemaname='public'
                 AND (tablename LIKE 'so%' OR tablename IN
                    ('atomic_units','inventory_items','inventory_movements'))
               ORDER BY tablename"""
        )
    )]
    return {name: connection.execute(__import__("sqlalchemy").text(f'SELECT count(*) FROM "{name}"')).scalar_one() for name in names}


def database_acceptance() -> dict[str, str]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from database import engine as application_engine
    from shared_operations.so2 import EstablishRelationship, RelationshipStatus, SO2Authority, SO2AuthorityError
    from shared_operations.so2.sql_repository import SQLSO2Repository

    url = make_url(application_engine.url)
    if url.host not in LOCAL or url.database != "xbos_track_b_dev":
        raise RuntimeError("SO_AGG_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    with application_engine.connect() as connection:
        action = _development_action(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        dev_before = _counts(connection)
        finance_dev_before = {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in FINANCE_TABLES}

    def selected(name: str, autocommit: bool = False):
        options = {"pool_pre_ping": True}
        if autocommit:
            options["isolation_level"] = "AUTOCOMMIT"
        return create_engine(url.set(database=name), **options)

    admin = selected("postgres", True)
    test = None
    success = False

    def drop() -> None:
        with admin.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),
                {"name": TEST_DB},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')

    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DB}" TEMPLATE template0')
        test = selected(TEST_DB)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        rendered = url.set(database=TEST_DB).render_as_string(hide_password=False)

        _run(command.upgrade, cfg, rendered, PREVIOUS)
        with test.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != PREVIOUS:
                raise RuntimeError("SO_AGG_PREDECESSOR_REPLAY")
            finance_before = {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in FINANCE_TABLES}

        _run(command.upgrade, cfg, rendered, HEAD)
        with test.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("SO_AGG_UPGRADE_HEAD")
            column = connection.execute(text("""SELECT is_nullable FROM information_schema.columns
                WHERE table_schema='public' AND table_name='so2_relationship_commands' AND column_name='tenant_id'""")).scalar_one_or_none()
            if column != "NO":
                raise RuntimeError("SO_AGG_SO2_TENANT_COLUMN")
            constraints = {row[0] for row in connection.execute(text("""SELECT conname FROM pg_constraint
                WHERE conrelid='public.so2_relationship_commands'::regclass"""))}
            required = {
                "uq_so2_relationship_commands_tenant_key",
                "fk_so2_relationship_commands_tenant",
                "fk_so2_relationship_commands_result",
            }
            if not required <= constraints:
                raise RuntimeError("SO_AGG_SO2_CONSTRAINTS")

        # Reversibility is proven before introducing state the historical schema
        # cannot represent (same command key in two tenants).
        _run(command.downgrade, cfg, rendered, PREVIOUS)
        _run(command.upgrade, cfg, rendered, HEAD)

        with test.begin() as connection:
            tenant_a = connection.execute(text("""INSERT INTO tenants(code,name,country_code,currency,locale,timezone)
                VALUES('SOAGGA','Aggregate Tenant A','CM','XAF','en-CM','Africa/Douala') RETURNING id""")).scalar_one()
            tenant_b = connection.execute(text("""INSERT INTO tenants(code,name,country_code,currency,locale,timezone)
                VALUES('SOAGGB','Aggregate Tenant B','CA','CAD','en-CA','America/Toronto') RETURNING id""")).scalar_one()
            party_a = connection.execute(text("""INSERT INTO parties(tenant_id,party_kind,display_name,status)
                VALUES(:t,'person','Aggregate Party A','active') RETURNING id,public_id"""), {"t": tenant_a}).one()
            party_b = connection.execute(text("""INSERT INTO parties(tenant_id,party_kind,display_name,status)
                VALUES(:t,'person','Aggregate Party B','active') RETURNING id,public_id"""), {"t": tenant_b}).one()

        now = datetime(2026, 8, 14, 22, 30, tzinfo=timezone.utc)
        same_key = "aggregate-shared-command-key"
        with Session(test, expire_on_commit=False) as session:
            with session.begin():
                def resolver(tenant_id, public_id):
                    row = session.execute(text("""SELECT id,tenant_id,public_id FROM parties
                        WHERE tenant_id=:tenant AND public_id=:public_id"""),
                        {"tenant": tenant_id, "public_id": str(public_id)}).first()
                    return SimpleNamespace(id=row.id, tenant_id=row.tenant_id, public_id=UUID(str(row.public_id))) if row else None
                authority = SO2Authority(
                    SQLSO2Repository(session),
                    party_resolver=resolver,
                    authorize=lambda *args: True,
                    validate_scope=lambda *args: True,
                    semantic_assigner=lambda payload: payload,
                    public_id_factory=uuid4,
                )
                first_command = EstablishRelationship(
                    same_key, tenant_a, UUID(str(party_a.public_id)), "client",
                    RelationshipStatus.ACTIVE, now,
                )
                second_command = EstablishRelationship(
                    same_key, tenant_b, UUID(str(party_b.public_id)), "supplier",
                    RelationshipStatus.ACTIVE, now,
                )
                first = authority.establish(first_command)
                replay = authority.establish(first_command)
                second = authority.establish(second_command)
                if replay.public_id != first.public_id or first.tenant_id == second.tenant_id:
                    raise RuntimeError("SO_AGG_TENANT_IDEMPOTENCY_REPLAY")
                try:
                    authority.establish(EstablishRelationship(
                        same_key, tenant_a, UUID(str(party_a.public_id)), "partner",
                        RelationshipStatus.ACTIVE, now,
                    ))
                except SO2AuthorityError as exc:
                    if exc.code != "SO2_COMMAND_CONFLICT":
                        raise
                else:
                    raise RuntimeError("SO_AGG_SAME_TENANT_COMMAND_CONFLICT_NOT_ENFORCED")

        with test.connect() as connection:
            if connection.execute(text("""SELECT count(*) FROM so2_relationship_commands
                WHERE command_key=:key"""), {"key": same_key}).scalar_one() != 2:
                raise RuntimeError("SO_AGG_TENANT_COMMAND_NAMESPACE")
            finance_after = {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in FINANCE_TABLES}
            if finance_after != finance_before:
                raise RuntimeError("SO_AGG_FINANCIAL_EFFECTS_CHANGED")

        # Composite FK must prevent a command in tenant A from claiming a
        # tenant B result row.
        with test.begin() as connection:
            result_b = connection.execute(text("""SELECT id FROM so2_operational_relationships
                WHERE tenant_id=:tenant LIMIT 1"""), {"tenant": tenant_b}).scalar_one()
            nested = connection.begin_nested()
            try:
                connection.execute(text("""INSERT INTO so2_relationship_commands
                    (tenant_id,command_key,request_fingerprint,command_type,result_id,completed_at)
                    VALUES(:tenant,'aggregate-cross-tenant-result',:fingerprint,'establish',:result,now())"""),
                    {"tenant": tenant_a, "fingerprint": "a" * 64, "result": result_b})
            except IntegrityError:
                nested.rollback()
            else:
                nested.rollback()
                raise RuntimeError("SO_AGG_CROSS_TENANT_RESULT_FK")

        # Resumable development adoption.
        if action == "UPGRADE":
            dev_cfg = Config(str(ROOT / "alembic_neutral.ini"))
            rendered_dev = url.render_as_string(hide_password=False)
            _run(command.upgrade, dev_cfg, rendered_dev, HEAD)
        with application_engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("SO_AGG_DEVELOPMENT_HEAD")
            dev_after = _counts(connection)
            finance_dev_after = {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in FINANCE_TABLES}
        if dev_after != dev_before:
            raise RuntimeError("SO_AGG_DEVELOPMENT_DATA_MUTATION")
        if finance_dev_after != finance_dev_before:
            raise RuntimeError("SO_AGG_DEVELOPMENT_FINANCE_MUTATION")

        success = True
        return {
            "clean_replay": "PASS",
            "upgrade": "PASS",
            "downgrade_reupgrade": "PASS",
            "tenant_idempotency": "PASS",
            "cross_tenant_result_integrity": "PASS",
            "development_adoption": action,
            "finance": "UNCHANGED",
            "cleanup": "PASS",
        }
    finally:
        if test is not None:
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
        print(f"SO_AGG_VERIFY=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("SO_AGG_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
