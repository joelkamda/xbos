#!/usr/bin/env python3
"""Verify PK4-PK6 and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "8f0034a6f3e7862a769891d84afa3aadf436c13c"
PREVIOUS = "pk0123_pack_manifest_lifecycle_037"
HEAD = "pk456_pack_conformance_templates_038"
CONTRACTS = ROOT / "contracts/packs/v1"


def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _canonical(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _set_url(config, url):
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def _run(operation, config, url, target):
    old = {k: os.environ.get(k) for k in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
    _set_url(config, url)
    os.environ.update(DATABASE_URL=url, MIGRATION_DATABASE_URL=url)
    try:
        operation(config, target)
    finally:
        for key, value in old.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)


def static_verify():
    from core.platform.architecture_contract import validate_pc0

    authority = _json("pk456_authority.json")
    interfaces = _json("pk456_public_interfaces.json")
    conformance = _json("pk456_conformance_schema.json")
    if (authority["source_checkpoint"], authority["previous_head"], authority["accepted_head"]) != (SOURCE, PREVIOUS, HEAD):
        raise RuntimeError("PK456_RELEASE_BOUNDARY")
    if authority["scope"] != ["PK4", "PK5", "PK6"] or authority["constitutional_rule"] != "pack_is_composition_not_authority":
        raise RuntimeError("PK456_SCOPE")
    if authority["authority_boundaries"]["finance"] != "UNCHANGED" or authority["authority_boundaries"]["shared_operations"] != "UNCHANGED":
        raise RuntimeError("PK456_BOUNDARY")
    if authority["production_dependency_changes"] != "NONE":
        raise RuntimeError("PK456_DEPENDENCIES")
    if authority["payments_product"]["accounting_workspace_off_means_finance_kernel_off"] is not False:
        raise RuntimeError("PK456_PAYMENTS_ONLY_FINANCE_BOUNDARY")
    if authority["payments_product"]["provider_execution_is_financial_truth"] is not False:
        raise RuntimeError("PK456_PROVIDER_EXECUTION_BOUNDARY")
    if "pack_platform.pk456_service.PK456Authority" not in interfaces["public"]:
        raise RuntimeError("PK456_PUBLIC_INTERFACE")
    required = set(conformance["certification"]["required_checks"])
    expected = {"architecture", "tenant_isolation", "migration_compatibility", "authorization", "semantics", "finance", "shared_operations", "xa", "manifest"}
    if required != expected:
        raise RuntimeError("PK456_CONFORMANCE_COVERAGE")
    up = (ROOT / "alembic_neutral/sql/pk456_pack_conformance_templates_up.sql").read_text(encoding="utf-8").lower()
    for marker in (
        "pk_pack_certifications", "pk_pack_certification_immutable", "pk_template_versions", "pk_template_version_immutable",
        "pk_tenant_template_bindings", "pk_tenant_template_overrides", "pk_tenant_template_history", "pk_template_history_immutable",
        "finance_kernel_required", "requirement_kind",
    ):
        if marker not in up:
            raise RuntimeError("PK456_SQL_BOUNDARY=" + marker)
    forbidden = (
        "insert into public.financial_events", "update public.financial_events", "insert into public.journal_entries",
        "insert into public.payment_settlements", "insert into public.permission_definitions", "insert into public.semantic_concepts",
        "update public.core_modules", "delete from public.financial_events",
    )
    if any(value in up for value in forbidden):
        raise RuntimeError("PK456_FORBIDDEN_AUTHORITY_WRITE")
    payments = _json("examples/payments_only_template.json")
    if payments["finance_kernel_required"] is not True or payments["finance_workspace_exposed"] is not False:
        raise RuntimeError("PK456_PAYMENTS_ONLY_TEMPLATE")
    if payments["financial_truth_owner"] != "Neutral Finance" or payments["provider_execution_owner"] != "product_integration_adapter":
        raise RuntimeError("PK456_PAYMENTS_AUTHORITY")
    field = _json("examples/neutral_field_service_template.json")
    if field["industry_semantic_ref"] == payments["industry_semantic_ref"]:
        raise RuntimeError("PK456_NEUTRALITY_PROFILES")
    report = validate_pc0(ROOT, validate_release=False)
    manifest = _json("pk456_release_manifest.json")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical(path) != item["sha256"]:
            raise RuntimeError("PK456_RELEASE_MISMATCH=" + item["path"])
    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": PREVIOUS,
        "accepted_head": HEAD,
        "pk4_conformance": "PASS",
        "pk5_template_registry": "PASS",
        "pk6_application_upgrade": "PASS",
        "payments_only_neutrality": "PASS",
        "finance": "UNCHANGED",
        "shared_operations": "UNCHANGED",
        "dependencies": "UNCHANGED",
        "pc0": report["status"],
        "release_artifacts": len(manifest["artifacts"]),
    }


def database_acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from database import engine
    from pack_platform import ActivatePack, InstallPack, PackAuthority, PackKind, PackManifest, RegisterPackVersion, StagePack
    from pack_platform.sql_repository import SQLPackRepository
    from pack_platform.pk456_contracts import (
        ApplyTemplate, CertifyPackVersion, ConformanceResult, PackCertificationEvidence, PlanTemplateApplication,
        PlanTemplateUpgrade, RegisterTemplateVersion, TemplateDefinition, TemplatePackRequirement,
        TemplateRequirementKind, UpgradeTemplate,
    )
    from pack_platform.pk456_service import PK456Authority, PK456AuthorityError
    from pack_platform.pk456_sql_repository import SQLPK456Repository

    url = make_url(engine.url)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or url.database != "xbos_track_b_dev":
        raise RuntimeError("PK456_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name = "xbos_pk456_test"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    test = None

    def drop():
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"), {"n": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')

    finance_tables = ("financial_events", "journal_entries", "financial_obligations", "payment_settlements", "outbox_messages", "idempotency_records")
    checks = {name: ConformanceResult.PASS for name in (
        "architecture", "tenant_isolation", "migration_compatibility", "authorization", "semantics", "finance", "shared_operations", "xa", "manifest"
    )}

    def template(version: str, allow_channel: bool = True):
        allowed = ("branding.display_name", "payments.default_channel") if allow_channel else ("branding.display_name",)
        defaults = {"workspaces": {"payments": True, "accounting": False, "sales": False, "inventory": False}, "payments": {"default_channel": "cash"}}
        if version == "2.0.0":
            defaults["payments"]["activity_page_size"] = 50
        return TemplateDefinition(
            "neutral.payments_only", version, "pk", "industry:financial_operations", "operating_model:payments_only",
            (
                TemplatePackRequirement("neutral.foundation", "1.0.0", TemplateRequirementKind.REQUIRED),
                TemplatePackRequirement("neutral.payments", "1.0.0", TemplateRequirementKind.REQUIRED),
            ),
            allowed, defaults, {}, {"primary_actions": ["receive", "pay", "transfer", "activity"], "accounting_workspace_exposed": False}, (), False, True,
        )

    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test = create_engine(url.set(database=name))
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        rendered = url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade, cfg, rendered, PREVIOUS)
        with test.begin() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != PREVIOUS:
                raise RuntimeError("PK456_PREDECESSOR_REPLAY")
            connection.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(13001,'PK45A','PK456 Tenant A','CM','XAF','en-CM','Africa/Douala'),(13002,'PK45B','PK456 Tenant B','CM','XAF','en-CM','Africa/Douala')"))
            before = tuple((table, connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()) for table in finance_tables)
        _run(command.upgrade, cfg, rendered, HEAD)
        with Session(test) as session, session.begin():
            packs = PackAuthority(SQLPackRepository(session))
            pk = PK456Authority(SQLPK456Repository(session))
            foundation = PackManifest("neutral.foundation", "1.0.0", "pk", PackKind.CAPABILITY, "1.0.0")
            payments = PackManifest("neutral.payments", "1.0.0", "pk", PackKind.CAPABILITY, "1.0.0")
            packs.register(RegisterPackVersion("register-foundation", foundation))
            packs.register(RegisterPackVersion("register-payments", payments))
            for tenant in (13001, 13002):
                for code, prefix in (("neutral.foundation", "foundation"), ("neutral.payments", "payments")):
                    state = packs.stage(StagePack(f"stage-{prefix}-{tenant}", tenant, code, "1.0.0"))
                    state = packs.install(InstallPack(f"install-{prefix}-{tenant}", tenant, code, "1.0.0", state.row_version))
                    packs.activate(ActivatePack(f"activate-{prefix}-{tenant}", tenant, code, "1.0.0", state.row_version))
            for code, evidence in (("neutral.foundation", "a" * 64), ("neutral.payments", "b" * 64)):
                cert = pk.certify(CertifyPackVersion(f"certify-{code}", code, "1.0.0", "pk-conformance", "1.0.0", PackCertificationEvidence(checks, (evidence,))))
                replay = pk.certify(CertifyPackVersion(f"certify-{code}", code, "1.0.0", "pk-conformance", "1.0.0", PackCertificationEvidence(checks, (evidence,))))
                if cert != replay:
                    raise RuntimeError("PK456_CERTIFICATION_REPLAY")
            pk.register_template(RegisterTemplateVersion("register-template-v1", template("1.0.0")))
            pk.register_template(RegisterTemplateVersion("register-template-v2", template("2.0.0")))
            pk.register_template(RegisterTemplateVersion("register-template-v3", template("3.0.0", allow_channel=False)))
            plan_a = pk.plan_application(PlanTemplateApplication(13001, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
            plan_a2 = pk.plan_application(PlanTemplateApplication(13001, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
            if plan_a != plan_a2 or plan_a.conflicts:
                raise RuntimeError("PK456_PLAN_NONDETERMINISTIC")
            plan_b = pk.plan_application(PlanTemplateApplication(13002, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "orange"}))
            state_a = pk.apply_template(ApplyTemplate("same-template-command", 13001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "mtn"}))
            replay_a = pk.apply_template(ApplyTemplate("same-template-command", 13001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "mtn"}))
            state_b = pk.apply_template(ApplyTemplate("same-template-command", 13002, "neutral.payments_only", "1.0.0", plan_b.plan_sha256, (), {"payments.default_channel": "orange"}))
            if replay_a != state_a or state_a.template_sha256 != state_b.template_sha256 or state_a.effective_configuration == state_b.effective_configuration:
                raise RuntimeError("PK456_MERCHANT_DIVERGENCE")
            if state_a.effective_configuration["workspaces"]["accounting"] is not False:
                raise RuntimeError("PK456_PAYMENTS_ONLY_WORKSPACE")
            try:
                with session.begin_nested():
                    pk.apply_template(ApplyTemplate("same-template-command", 13001, "neutral.payments_only", "1.0.0", plan_a.plan_sha256, (), {"payments.default_channel": "cash"}))
            except PK456AuthorityError as exc:
                if exc.code != "PK456_COMMAND_CONFLICT":
                    raise
            else:
                raise RuntimeError("PK456_CHANGED_REPLAY_ACCEPTED")
            unsafe = pk.plan_upgrade(PlanTemplateUpgrade(13001, "neutral.payments_only", "3.0.0"))
            if "override_not_allowed:payments.default_channel" not in unsafe.conflicts:
                raise RuntimeError("PK456_UPGRADE_CONFLICT_MISSED")
            upgrade = pk.plan_upgrade(PlanTemplateUpgrade(13001, "neutral.payments_only", "2.0.0"))
            if upgrade.conflicts:
                raise RuntimeError("PK456_SAFE_UPGRADE_CONFLICT")
            upgraded = pk.upgrade_template(UpgradeTemplate("upgrade-a", 13001, "neutral.payments_only", "2.0.0", upgrade.plan_sha256, state_a.row_version, "explicit merchant acceptance"))
            if upgraded.version != "2.0.0" or upgraded.overrides.get("payments.default_channel") != "mtn":
                raise RuntimeError("PK456_UPGRADE_PRESERVATION")
        with test.begin() as connection:
            cert_id = connection.execute(text("SELECT id FROM pk_pack_certifications LIMIT 1")).scalar_one()
            try:
                with connection.begin_nested():
                    connection.execute(text("UPDATE pk_pack_certifications SET result='fail' WHERE id=:i"), {"i": cert_id})
            except DBAPIError:
                pass
            else:
                raise RuntimeError("PK456_CERTIFICATION_MUTATION_ACCEPTED")
            version_id = connection.execute(text("SELECT id FROM pk_template_versions LIMIT 1")).scalar_one()
            try:
                with connection.begin_nested():
                    connection.execute(text("UPDATE pk_template_versions SET template_version='9.9.9' WHERE id=:i"), {"i": version_id})
            except DBAPIError:
                pass
            else:
                raise RuntimeError("PK456_TEMPLATE_MUTATION_ACCEPTED")
            history_id = connection.execute(text("SELECT id FROM pk_tenant_template_history LIMIT 1")).scalar_one()
            try:
                with connection.begin_nested():
                    connection.execute(text("UPDATE pk_tenant_template_history SET reason='rewrite' WHERE id=:i"), {"i": history_id})
            except DBAPIError:
                pass
            else:
                raise RuntimeError("PK456_HISTORY_MUTATION_ACCEPTED")
            after = tuple((table, connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()) for table in finance_tables)
            if after != before:
                raise RuntimeError("PK456_FINANCIAL_EFFECTS_CHANGED")
        _run(command.downgrade, cfg, rendered, PREVIOUS)
        _run(command.upgrade, cfg, rendered, HEAD)
        with test.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("PK456_REUPGRADE")
            if connection.execute(text("SELECT to_regclass('public.pk_template_versions')")).scalar_one() is None:
                raise RuntimeError("PK456_REUPGRADE_SCHEMA")
        with engine.connect() as connection:
            dev = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl = url.render_as_string(hide_password=False)
        if dev == PREVIOUS:
            _run(command.upgrade, Config(str(ROOT / "alembic_neutral.ini")), devurl, HEAD)
        elif dev == HEAD:
            with engine.connect() as connection:
                if connection.execute(text("SELECT to_regclass('public.pk_template_versions')")).scalar_one() is None:
                    raise RuntimeError("PK456_DEVELOPMENT_SCHEMA_MISSING")
        else:
            raise RuntimeError("PK456_DEVELOPMENT_HEAD_UNSAFE=" + dev)
        return {
            "disposable_rehearsal": "PASS",
            "development_adoption": "PASS",
            "pack_certification": "PASS",
            "template_registry": "PASS",
            "template_application": "PASS",
            "template_upgrade": "PASS",
            "merchant_divergence": "PASS",
            "tenant_idempotency": "PASS",
            "payments_only_neutrality": "PASS",
            "financial_effects": "UNCHANGED",
        }
    finally:
        if test:
            test.dispose()
        drop()
        admin.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()
    result = static_verify()
    if args.acceptance:
        result.update(database_acceptance())
    print(json.dumps(result, indent=2, sort_keys=True))
    print("PK456_VERIFY=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PK456_VERIFY=FAIL\n" + str(exc))
        raise SystemExit(1)
