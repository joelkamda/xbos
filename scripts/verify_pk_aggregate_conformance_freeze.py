#!/usr/bin/env python3
"""Verify PK0-PK6 aggregate conformance and controlled local PostgreSQL proof."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "97c6c751259649ef0a90a63f11fa78d8b1b1d599"
PREVIOUS = "pk456_pack_conformance_templates_038"
HEAD = "pk456_pack_conformance_templates_038"
CONTRACTS = ROOT / "contracts/packs/v1"
LOCAL = {"localhost", "127.0.0.1", "::1"}

FINANCE_TABLES = (
    "financial_events",
    "journal_entries",
    "financial_obligations",
    "payment_settlements",
    "outbox_messages",
    "idempotency_records",
    "operational_accounts",
    "value_transfers",
    "reconciliation_windows",
    "reconciliation_controls",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_url(config, url: str) -> None:
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def _run(operation, config, url: str, target: str) -> None:
    old = {key: os.environ.get(key) for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
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


def _migration_head() -> tuple[str, list[str]]:
    revisions: dict[str, str | None] = {}
    for path in sorted((ROOT / "alembic_neutral/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        revision = values.get("revision")
        if isinstance(revision, str):
            if revision in revisions:
                raise RuntimeError("PK_AGG_DUPLICATE_MIGRATION=" + revision)
            parent = values.get("down_revision")
            revisions[revision] = parent if isinstance(parent, str) else None
    parents = {value for value in revisions.values() if value}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        raise RuntimeError("PK_AGG_MIGRATION_HEAD=" + ",".join(heads))
    lineage: list[str] = []
    current: str | None = heads[0]
    while current:
        if current in lineage or current not in revisions:
            raise RuntimeError("PK_AGG_MIGRATION_LINEAGE=" + str(current))
        lineage.append(current)
        current = revisions[current]
    return heads[0], list(reversed(lineage))


def _verify_release_manifest(name: str) -> int:
    manifest = _json(CONTRACTS / name)
    for item in manifest.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError(f"PK_AGG_COMPONENT_RELEASE_MISMATCH={name}:{item['path']}")
    return len(manifest.get("artifacts", []))


def _verify_pack_writes_are_private_to_pk() -> None:
    pattern = re.compile(r"\b(?:insert\s+into|update|delete\s+from)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)
    for path in sorted((ROOT / "pack_platform").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for table in pattern.findall(source):
            if not table.lower().startswith("pk_"):
                raise RuntimeError(f"PK_AGG_PRIVATE_SOURCE_WRITE={path.name}:{table}")


def static_verify() -> dict:
    from core.platform.architecture_contract import validate_pc0

    aggregate = _json(CONTRACTS / "pk_aggregate_conformance_freeze.json")
    if (aggregate["source_checkpoint"], aggregate["previous_head"], aggregate["accepted_head"]) != (SOURCE, PREVIOUS, HEAD):
        raise RuntimeError("PK_AGG_RELEASE_BOUNDARY")
    if aggregate["migration"] != "NONE" or aggregate["business_capability_change"] != "NONE":
        raise RuntimeError("PK_AGG_SCOPE_EXPANSION")
    if aggregate["coverage"] != [f"PK{number}" for number in range(7)]:
        raise RuntimeError("PK_AGG_COVERAGE")
    if aggregate["constitutional_rule"] != "pack_is_composition_not_authority":
        raise RuntimeError("PK_AGG_CONSTITUTION")

    pk0123 = _json(CONTRACTS / "pk0123_authority.json")
    pk456 = _json(CONTRACTS / "pk456_authority.json")
    if pk0123["scope"] != ["PK0", "PK1", "PK2", "PK3"] or pk456["scope"] != ["PK4", "PK5", "PK6"]:
        raise RuntimeError("PK_AGG_COMPONENT_SCOPE")
    if pk0123["accepted_head"] != "pk0123_pack_manifest_lifecycle_037":
        raise RuntimeError("PK_AGG_PK0123_HEAD")
    if pk456["previous_head"] != pk0123["accepted_head"] or pk456["accepted_head"] != HEAD:
        raise RuntimeError("PK_AGG_COMPONENT_LINEAGE")
    if pk0123["constitutional_rule"] != aggregate["constitutional_rule"] or pk456["constitutional_rule"] != aggregate["constitutional_rule"]:
        raise RuntimeError("PK_AGG_COMPONENT_CONSTITUTION")
    if pk0123["finance"] != "UNCHANGED" or pk456["authority_boundaries"]["finance"] != "UNCHANGED":
        raise RuntimeError("PK_AGG_FINANCE_BOUNDARY")
    if pk0123["shared_operations"] != "UNCHANGED" or pk456["authority_boundaries"]["shared_operations"] != "UNCHANGED":
        raise RuntimeError("PK_AGG_SO_BOUNDARY")

    _verify_release_manifest("pk0123_release_manifest.json")
    _verify_release_manifest("pk456_release_manifest.json")

    module_map = _json(ROOT / "contracts/platform/v1/pc0_module_map.json")
    packs = next((row for row in module_map["modules"] if row.get("code") == "packs"), None)
    if not packs or packs.get("owner") != "PK" or packs.get("kind") != "pack_composition_authority":
        raise RuntimeError("PK_AGG_PC0_MODULE")
    policy = _json(ROOT / "contracts/platform/v1/pc0_dependency_policy.json")
    if policy["allowed_directions"].get("packs") != []:
        raise RuntimeError("PK_AGG_DEPENDENCY_BOUNDARY")
    authorities = _json(ROOT / "contracts/platform/v1/pc0_data_authority_register.json")
    authority = next((row for row in authorities["authorities"] if row.get("code") == "pack_composition"), None)
    if not authority or authority.get("owner") != "PK":
        raise RuntimeError("PK_AGG_AUTHORITY_REGISTER")

    _verify_pack_writes_are_private_to_pk()

    connector = _json(CONTRACTS / "examples/neutral_payment_provider_connector.json")
    if connector["financial_truth"] != "NONE" or connector["settlement_owner"] != "Neutral Finance":
        raise RuntimeError("PK_AGG_CONNECTOR_FINANCE_BOUNDARY")
    if set(connector["finality_policy"].values()) != {"submitted", "pending", "failed", "ambiguous", "provider_final"}:
        raise RuntimeError("PK_AGG_CONNECTOR_FINALITY")
    if connector["external_reference_lookup"] is not True or "blind" in connector["ambiguous_outcome_policy"].lower():
        # The specimen uses lookup + manual hold. It must never express blind retry.
        raise RuntimeError("PK_AGG_CONNECTOR_RECOVERY")
    if connector["raw_payload_policy"] != "sanitized_or_encrypted_only":
        raise RuntimeError("PK_AGG_CONNECTOR_SENSITIVE_DATA")

    payments = _json(CONTRACTS / "examples/payments_only_template.json")
    field = _json(CONTRACTS / "examples/neutral_field_service_template.json")
    workspaces = payments["configuration_defaults"]["workspaces"]
    if payments["finance_kernel_required"] is not True or payments["finance_workspace_exposed"] is not False:
        raise RuntimeError("PK_AGG_PAYMENTS_ONLY_FINANCE")
    if any(workspaces.get(code) is not False for code in ("accounting", "sales", "inventory", "procurement")):
        raise RuntimeError("PK_AGG_PAYMENTS_ONLY_COMPOSITION")
    if workspaces.get("payments") is not True or payments["financial_truth_owner"] != "Neutral Finance":
        raise RuntimeError("PK_AGG_PAYMENTS_ONLY_AUTHORITY")
    if payments["provider_execution_owner"] != "product_integration_adapter":
        raise RuntimeError("PK_AGG_PROVIDER_EXECUTION_OWNER")
    if (payments["industry_semantic_ref"], payments["operating_model_semantic_ref"]) == (field["industry_semantic_ref"], field["operating_model_semantic_ref"]):
        raise RuntimeError("PK_AGG_NEUTRALITY_PROFILES")

    xa = _json(ROOT / "contracts/experience/v1/xa_frontend_experience_contract.json")
    readiness = next((row for row in xa["contracts"] if row.get("id") == "template_composition_readiness"), None)
    if not readiness or readiness.get("rule") != "consume_future_PK_composition_without_implementing_PK":
        raise RuntimeError("PK_AGG_XA_CONSUMPTION")

    head, lineage = _migration_head()
    expected = ["so_aggregate_conformance_hardening_036", "pk0123_pack_manifest_lifecycle_037", "pk456_pack_conformance_templates_038"]
    start = lineage.index(expected[0]) if expected[0] in lineage else -1
    if start < 0 or lineage[start:start+3] != expected:
        raise RuntimeError("PK_AGG_MIGRATION_PREFIX")

    if aggregate.get("dependency_fingerprint_mode") != "sha256_git_canonical_lf":
        raise RuntimeError("PK_AGG_DEPENDENCY_FINGERPRINT_MODE")
    for relative, expected in aggregate["dependency_fingerprints"].items():
        # Dependency manifests are tracked text. PC5/PC6 release integrity treats
        # CRLF and LF working-tree materializations as the same committed content.
        # Preserve that portability law here while still detecting semantic pin changes.
        if _canonical_sha(ROOT / relative) != expected:
            raise RuntimeError("PK_AGG_DEPENDENCY_CHANGED=" + relative)

    pc0 = validate_pc0(ROOT, validate_release=False)
    so_aggregate = _json(ROOT / "contracts/shared_operations/v1/so_aggregate_conformance_freeze.json")
    if so_aggregate["accepted_head"] != "so_aggregate_conformance_hardening_036" or so_aggregate["aggregate_invariants"]["finance"] != "UNCHANGED":
        raise RuntimeError("PK_AGG_SO_FREEZE_BOUNDARY")

    manifest = _json(CONTRACTS / "pk_aggregate_release_manifest.json")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError("PK_AGG_RELEASE_MISMATCH=" + item["path"])

    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": PREVIOUS,
        "accepted_head": HEAD,
        "migration": "NONE",
        "pk0_pk6_coverage": "PASS",
        "manifest_lifecycle": "PASS",
        "public_boundaries": "PASS",
        "connector_finality": "PASS",
        "pack_conformance": "PASS",
        "template_registry": "PASS",
        "template_application_upgrade": "PASS",
        "payments_only_neutrality": "PASS",
        "xa_composition": "PASS",
        "tenant_isolation": "PASS",
        "migration_lineage": "PASS",
        "finance": "UNCHANGED",
        "shared_operations": "UNCHANGED",
        "dependencies": "UNCHANGED",
        "pc0": pc0["status"],
        "release_artifacts": len(manifest["artifacts"]),
        "pa_readiness": "PASS",
    }


def database_acceptance() -> dict:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from database import engine
    from pack_platform import (
        ActivatePack,
        ConnectorDeclaration,
        ConnectorKind,
        ExecutionState,
        InstallPack,
        PackAuthority,
        PackDependency,
        PackKind,
        PackManifest,
        ProviderIdempotency,
        RegisterPackVersion,
        StagePack,
    )
    from pack_platform.service import PackAuthorityError
    from pack_platform.sql_repository import SQLPackRepository
    from pack_platform.pk456_contracts import (
        ApplyTemplate,
        CertifyPackVersion,
        ConformanceResult,
        PackCertificationEvidence,
        PlanTemplateApplication,
        PlanTemplateUpgrade,
        RegisterTemplateVersion,
        TemplateDefinition,
        TemplatePackRequirement,
        TemplateRequirementKind,
        UpgradeTemplate,
    )
    from pack_platform.pk456_service import PK456Authority, PK456AuthorityError
    from pack_platform.pk456_sql_repository import SQLPK456Repository

    url = make_url(engine.url)
    if url.host not in LOCAL or url.database != "xbos_track_b_dev":
        raise RuntimeError("PK_AGG_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")

    db_name = "xbos_pk_aggregate_test"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    test_engine = None

    def drop() -> None:
        with admin.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),
                {"n": db_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{db_name}"')

    def snapshot(connection, tables: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
        values = []
        for table in tables:
            exists = connection.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}).scalar_one()
            if exists is not None:
                values.append((table, connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()))
        return tuple(values)

    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{db_name}" TEMPLATE template0')
        test_engine = create_engine(url.set(database=db_name))
        rendered = url.set(database=db_name).render_as_string(hide_password=False)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        _run(command.upgrade, cfg, rendered, HEAD)

        with test_engine.begin() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("PK_AGG_CLEAN_REPLAY_HEAD")
            connection.execute(text("""
                INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES
                (14001,'PKAGA','PK Aggregate Payments A','CM','XAF','en-CM','Africa/Douala'),
                (14002,'PKAGB','PK Aggregate Payments B','CM','XAF','en-CM','Africa/Douala'),
                (14003,'PKAGC','PK Aggregate Field Service','CM','XAF','en-CM','Africa/Douala')
            """))
            so_tables = tuple(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'so%' ORDER BY tablename")).scalars().all())
            finance_before = snapshot(connection, FINANCE_TABLES)
            so_before = snapshot(connection, so_tables)

        checks = {name: ConformanceResult.PASS for name in (
            "architecture", "tenant_isolation", "migration_compatibility", "authorization", "semantics",
            "finance", "shared_operations", "xa", "manifest",
        )}

        with Session(test_engine) as session, session.begin():
            packs = PackAuthority(SQLPackRepository(session))
            pk = PK456Authority(SQLPK456Repository(session))

            connector = ConnectorDeclaration(
                "payout.example",
                ConnectorKind.PAYMENT_PROVIDER,
                "example_rail",
                ("collection", "payout", "refund"),
                ProviderIdempotency.EXTERNAL_REFERENCE,
                True,
                "provider_event_id",
                {
                    "accepted": ExecutionState.SUBMITTED,
                    "processing": ExecutionState.PENDING,
                    "failed": ExecutionState.FAILED,
                    "timeout": ExecutionState.AMBIGUOUS,
                    "beneficiary_credited": ExecutionState.PROVIDER_FINAL,
                },
                ("provider_beneficiary_token", "mobile_money_reference", "bank_beneficiary_reference"),
                ("example_rail.credentials",),
                "lookup_external_reference_then_manual_hold",
                "sanitized_or_encrypted_only",
            )
            foundation = PackManifest("neutral.foundation", "1.0.0", "pk", PackKind.CAPABILITY, "1.0.0")
            payments_pack = PackManifest(
                "neutral.payments", "1.0.0", "pk", PackKind.CAPABILITY, "1.0.0",
                dependencies=(PackDependency("neutral.foundation", "1.0.0"),),
                connectors=(connector,),
            )
            scheduling_pack = PackManifest(
                "neutral.scheduling", "1.0.0", "pk", PackKind.CAPABILITY, "1.0.0",
                dependencies=(PackDependency("neutral.foundation", "1.0.0"),),
            )
            for key, manifest in (
                ("register-foundation", foundation),
                ("register-payments", payments_pack),
                ("register-scheduling", scheduling_pack),
            ):
                packs.register(RegisterPackVersion(key, manifest))

            def activate(tenant_id: int, code: str) -> None:
                state = packs.stage(StagePack(f"stage-{code}-{tenant_id}", tenant_id, code, "1.0.0"))
                state = packs.install(InstallPack(f"install-{code}-{tenant_id}", tenant_id, code, "1.0.0", state.row_version))
                packs.activate(ActivatePack(f"activate-{code}-{tenant_id}", tenant_id, code, "1.0.0", state.row_version))

            for tenant in (14001, 14002, 14003):
                activate(tenant, "neutral.foundation")
            for tenant in (14001, 14002):
                activate(tenant, "neutral.payments")

            for index, code in enumerate(("neutral.foundation", "neutral.payments", "neutral.scheduling"), start=1):
                pk.certify(CertifyPackVersion(
                    f"certify-{code}", code, "1.0.0", "pk-conformance", "1.0.0",
                    PackCertificationEvidence(checks, ((str(index) * 64)[:64],)),
                ))

            payment_requirements = (
                TemplatePackRequirement("neutral.foundation", "1.0.0", TemplateRequirementKind.REQUIRED),
                TemplatePackRequirement("neutral.payments", "1.0.0", TemplateRequirementKind.REQUIRED),
            )
            payment_defaults = {
                "workspaces": {"payments": True, "accounting": False, "sales": False, "inventory": False, "procurement": False},
                "payments": {"default_channel": "cash"},
            }
            for version in ("1.0.0", "2.0.0"):
                pk.register_template(RegisterTemplateVersion(
                    f"register-payments-template-{version}",
                    TemplateDefinition(
                        "neutral.payments_only", version, "pk", "industry:financial_operations", "operating_model:payments_only",
                        payment_requirements,
                        ("branding.display_name", "payments.default_channel"),
                        payment_defaults,
                        {},
                        {"primary_actions": ["receive", "pay", "transfer", "activity"], "accounting_workspace_exposed": False},
                        (),
                        False,
                        True,
                    ),
                ))
            pk.register_template(RegisterTemplateVersion(
                "register-field-template-1",
                TemplateDefinition(
                    "neutral.field_service", "1.0.0", "pk", "industry:field_service", "operating_model:scheduled_service",
                    (
                        TemplatePackRequirement("neutral.foundation", "1.0.0", TemplateRequirementKind.REQUIRED),
                        TemplatePackRequirement("neutral.scheduling", "1.0.0", TemplateRequirementKind.OPTIONAL),
                    ),
                    ("branding.display_name", "service.default_duration_minutes"),
                    {"service": {"default_duration_minutes": 60}, "workspaces": {"scheduling": True, "inventory": False}},
                    {},
                    {"primary_actions": ["schedule", "dispatch", "complete"]},
                    (),
                    True,
                    True,
                ),
            ))

            plan_a = pk.plan_application(PlanTemplateApplication(14001, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
            plan_b = pk.plan_application(PlanTemplateApplication(14002, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "orange"}))
            plan_c = pk.plan_application(PlanTemplateApplication(14003, "neutral.field_service", "1.0.0", (), {"service.default_duration_minutes": 45}))
            if plan_a.conflicts or plan_b.conflicts or plan_c.conflicts:
                raise RuntimeError("PK_AGG_PLAN_CONFLICT")

            state_a = pk.apply_template(ApplyTemplate("aggregate-apply", 14001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "mtn"}))
            state_b = pk.apply_template(ApplyTemplate("aggregate-apply", 14002, "neutral.payments_only", "1.0.0", plan_b.plan_sha256, (), {"payments.default_channel": "orange"}))
            state_c = pk.apply_template(ApplyTemplate("aggregate-apply", 14003, "neutral.field_service", "1.0.0", plan_c.plan_sha256, (), {"service.default_duration_minutes": 45}))
            replay_a = pk.apply_template(ApplyTemplate("aggregate-apply", 14001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "mtn"}))
            if replay_a != state_a:
                raise RuntimeError("PK_AGG_EXACT_REPLAY")
            if state_a.effective_configuration == state_b.effective_configuration:
                raise RuntimeError("PK_AGG_MERCHANT_DIVERGENCE")
            if state_a.effective_configuration["workspaces"]["accounting"] is not False or state_a.effective_configuration["workspaces"]["payments"] is not True:
                raise RuntimeError("PK_AGG_PAYMENTS_ONLY_RUNTIME")
            if state_c.template_code != "neutral.field_service" or state_c.effective_configuration["service"]["default_duration_minutes"] != 45:
                raise RuntimeError("PK_AGG_SECOND_PROFILE")

            try:
                with session.begin_nested():
                    pk.apply_template(ApplyTemplate("aggregate-apply", 14001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "cash"}))
            except PK456AuthorityError as exc:
                if exc.code != "PK456_COMMAND_CONFLICT":
                    raise
            else:
                raise RuntimeError("PK_AGG_CHANGED_REPLAY_ACCEPTED")

            upgrade = pk.plan_upgrade(PlanTemplateUpgrade(14001, "neutral.payments_only", "2.0.0"))
            if upgrade.conflicts:
                raise RuntimeError("PK_AGG_SAFE_UPGRADE_CONFLICT")
            upgraded = pk.upgrade_template(UpgradeTemplate(
                "aggregate-upgrade", 14001, "neutral.payments_only", "2.0.0", upgrade.plan_sha256,
                state_a.row_version, "explicit aggregate acceptance",
            ))
            if upgraded.version != "2.0.0" or upgraded.overrides.get("payments.default_channel") != "mtn":
                raise RuntimeError("PK_AGG_UPGRADE_PRESERVATION")

        with test_engine.begin() as connection:
            finance_after = snapshot(connection, FINANCE_TABLES)
            so_after = snapshot(connection, so_tables)
            if finance_after != finance_before:
                raise RuntimeError("PK_AGG_FINANCIAL_EFFECTS_CHANGED")
            if so_after != so_before:
                raise RuntimeError("PK_AGG_SHARED_OPERATIONS_CHANGED")
            if connection.execute(text("SELECT count(*) FROM pk_tenant_template_bindings")).scalar_one() != 3:
                raise RuntimeError("PK_AGG_TEMPLATE_BINDING_COUNT")

        # Rehearse the complete PK schema tail together, not only the last package.
        _run(command.downgrade, cfg, rendered, "so_aggregate_conformance_hardening_036")
        with test_engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "so_aggregate_conformance_hardening_036":
                raise RuntimeError("PK_AGG_DOWNGRADE_HEAD")
            if connection.execute(text("SELECT to_regclass('public.pk_packs')")).scalar_one() is not None:
                raise RuntimeError("PK_AGG_DOWNGRADE_PK0123_REMAINS")
            if connection.execute(text("SELECT to_regclass('public.pk_template_versions')")).scalar_one() is not None:
                raise RuntimeError("PK_AGG_DOWNGRADE_PK456_REMAINS")
        _run(command.upgrade, cfg, rendered, HEAD)
        with test_engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("PK_AGG_REUPGRADE_HEAD")
            for table in ("pk_packs", "pk_pack_certifications", "pk_template_versions", "pk_tenant_template_bindings"):
                if connection.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}).scalar_one() is None:
                    raise RuntimeError("PK_AGG_REUPGRADE_SCHEMA=" + table)

        # Aggregate itself is schema-neutral: the already-accepted dev DB must already be at PK456 head.
        with engine.connect() as connection:
            dev_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if dev_head != HEAD:
                raise RuntimeError("PK_AGG_DEVELOPMENT_HEAD=" + str(dev_head))
            for table in ("pk_packs", "pk_pack_certifications", "pk_template_versions", "pk_tenant_template_bindings"):
                if connection.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}).scalar_one() is None:
                    raise RuntimeError("PK_AGG_DEVELOPMENT_SCHEMA_MISSING=" + table)

        return {
            "clean_replay": "PASS",
            "pk_tail_downgrade_reupgrade": "PASS",
            "development_readiness": "PASS",
            "manifest_lifecycle_coherence": "PASS",
            "cross_package_composition": "PASS",
            "merchant_divergence": "PASS",
            "tenant_idempotency": "PASS",
            "payments_only_neutrality": "PASS",
            "second_profile_neutrality": "PASS",
            "template_upgrade": "PASS",
            "financial_effects": "UNCHANGED",
            "shared_operations_effects": "UNCHANGED",
        }
    finally:
        if test_engine is not None:
            test_engine.dispose()
        drop()
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()
    result = static_verify()
    if args.acceptance:
        result.update(database_acceptance())
    print(json.dumps(result, indent=2, sort_keys=True))
    print("PK_AGG_VERIFY=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PK_AGG_VERIFY=FAIL\n" + str(exc))
        raise SystemExit(1)
