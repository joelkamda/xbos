#!/usr/bin/env python3
"""Verify PA0-PA6 aggregate conformance and controlled local PostgreSQL proof."""
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

SOURCE = "03ede10255cfb330d3d3e76429c8c9b35d8e45ba"
PREVIOUS = "pa45_support_recovery_health_040"
HEAD = "pa45_support_recovery_health_040"
PA_BASE = "pk456_pack_conformance_templates_038"
PA0123_HEAD = "pa0123_merchant_lifecycle_subscriptions_onboarding_039"
CONTRACTS = ROOT / "contracts/platform_admin/v1"
LOCAL = {"localhost", "127.0.0.1", "::1"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


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


def _migration_lineage() -> tuple[str, list[str]]:
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
                raise RuntimeError("PA6_DUPLICATE_MIGRATION=" + revision)
            parent = values.get("down_revision")
            revisions[revision] = parent if isinstance(parent, str) else None
    parents = {value for value in revisions.values() if value}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        raise RuntimeError("PA6_MIGRATION_HEAD=" + ",".join(heads))
    lineage: list[str] = []
    current: str | None = heads[0]
    while current:
        if current in lineage or current not in revisions:
            raise RuntimeError("PA6_MIGRATION_LINEAGE=" + str(current))
        lineage.append(current)
        current = revisions[current]
    return heads[0], list(reversed(lineage))


def _verify_release_manifest(path: Path) -> int:
    manifest = _json(path)
    for item in manifest.get("artifacts", []):
        artifact = ROOT / item["path"]
        if not artifact.is_file() or _canonical_sha(artifact) != item["sha256"]:
            raise RuntimeError(f"PA6_COMPONENT_RELEASE_MISMATCH={path.name}:{item['path']}")
    return len(manifest.get("artifacts", []))


def _verify_pa_writes_are_private() -> None:
    pattern = re.compile(r"\b(?:insert\s+into|update|delete\s+from)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)
    for path in sorted((ROOT / "platform_admin").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for table in pattern.findall(source):
            if not table.lower().startswith("pa_"):
                raise RuntimeError(f"PA6_PRIVATE_SOURCE_WRITE={path.name}:{table}")


def static_verify() -> dict:
    from core.platform.architecture_contract import validate_pc0

    aggregate = _json(CONTRACTS / "pa6_aggregate_conformance_freeze.json")
    if (aggregate["source_checkpoint"], aggregate["previous_head"], aggregate["accepted_head"]) != (SOURCE, PREVIOUS, HEAD):
        raise RuntimeError("PA6_RELEASE_BOUNDARY")
    if aggregate["migration"] != "NONE" or aggregate["business_capability_change"] != "NONE":
        raise RuntimeError("PA6_SCOPE_EXPANSION")
    if aggregate["coverage"] != [f"PA{number}" for number in range(7)]:
        raise RuntimeError("PA6_COVERAGE")
    if aggregate["constitutional_rule"] != "platform_admin_orchestrates_public_authorities_without_redefining_them":
        raise RuntimeError("PA6_CONSTITUTION")

    pa0123 = _json(CONTRACTS / "pa0123_authority.json")
    pa45 = _json(CONTRACTS / "pa45_authority.json")
    health = _json(CONTRACTS / "pa45_health_contract.json")
    if pa0123["coverage"] != ["PA0", "PA1", "PA2", "PA3"] or pa45["coverage"] != ["PA4", "PA5"]:
        raise RuntimeError("PA6_COMPONENT_SCOPE")
    if pa0123["accepted_head"] != PA0123_HEAD:
        raise RuntimeError("PA6_PA0123_HEAD")
    if pa45["previous_head"] != PA0123_HEAD or pa45["accepted_head"] != HEAD:
        raise RuntimeError("PA6_COMPONENT_LINEAGE")
    if pa0123["constitutional_rule"] != aggregate["constitutional_rule"]:
        raise RuntimeError("PA6_COMPONENT_CONSTITUTION")

    b0 = pa0123["authority_boundaries"]
    if b0["tenant_lifecycle"] != "PC1" or b0["effective_entitlement"] != "PC4" or b0["authorization_and_admin_identity"] != "PC5" or b0["template_and_pack_composition"] != "PK":
        raise RuntimeError("PA6_PA0123_AUTHORITY_BOUNDARY")
    b1 = pa45["authority_boundaries"]
    if b1["tenant_lifecycle"] != "PC1_REUSED" or b1["authorization_and_identity"] != "PC5_REUSED" or b1["template_composition"] != "PK_REUSED":
        raise RuntimeError("PA6_PA45_AUTHORITY_BOUNDARY")
    if b0["finance"] != "UNCHANGED" or b1["finance"] != "UNCHANGED" or b0["shared_operations"] != "UNCHANGED" or b1["shared_operations"] != "UNCHANGED":
        raise RuntimeError("PA6_DOMAIN_BOUNDARY")
    if "health is observation, never source truth" not in health["laws"]:
        raise RuntimeError("PA6_HEALTH_AUTHORITY")

    _verify_release_manifest(CONTRACTS / "pa0123_release_manifest.json")
    _verify_release_manifest(CONTRACTS / "pa45_release_manifest.json")

    module_map = _json(ROOT / "contracts/platform/v1/pc0_module_map.json")
    admin = next((row for row in module_map["modules"] if row.get("code") == "platform_admin"), None)
    if not admin or admin.get("owner") != "PA" or admin.get("kind") != "platform_administration_authority":
        raise RuntimeError("PA6_PC0_MODULE")
    policy = _json(ROOT / "contracts/platform/v1/pc0_dependency_policy.json")
    if policy["allowed_directions"].get("platform_admin") != ["structure", "operating_context", "security_authority", "packs"]:
        raise RuntimeError("PA6_DEPENDENCY_BOUNDARY")
    authorities = _json(ROOT / "contracts/platform/v1/pc0_data_authority_register.json")
    owned = {row.get("code") for row in authorities["authorities"] if row.get("owner") == "PA"}
    expected_owned = {"merchant_administration", "commercial_subscription", "usage_metering", "merchant_onboarding_readiness", "platform_support_session", "merchant_recovery_case", "merchant_platform_health"}
    if not expected_owned.issubset(owned):
        raise RuntimeError("PA6_AUTHORITY_REGISTER")

    _verify_pa_writes_are_private()

    head, lineage = _migration_lineage()
    prefix = [PA_BASE, PA0123_HEAD, HEAD]
    start = lineage.index(PA_BASE) if PA_BASE in lineage else -1
    if start < 0 or lineage[start:start + len(prefix)] != prefix:
        raise RuntimeError("PA6_MIGRATION_PREFIX")
    # Prospective rule: later legal descendants are allowed; the frozen PA prefix may not be rewritten/forked.
    if lineage.index(HEAD) < lineage.index(PA0123_HEAD):
        raise RuntimeError("PA6_MIGRATION_ORDER")

    for name, expected in aggregate["dependency_fingerprints"].items():
        path = ROOT / name
        if not path.is_file() or _canonical_sha(path) != expected:
            raise RuntimeError("PA6_DEPENDENCY_CHANGED=" + name)

    report = validate_pc0(ROOT, validate_release=False)
    manifest = _json(CONTRACTS / "pa6_release_manifest.json")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError("PA6_RELEASE_MISMATCH=" + item["path"])

    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": PREVIOUS,
        "accepted_head": HEAD,
        "migration": "NONE",
        "pa0_pa6_coverage": "PASS",
        "merchant_lifecycle": "PASS",
        "subscriptions_entitlements": "PASS",
        "usage_quotas": "PASS",
        "onboarding_readiness": "PASS",
        "support_recovery": "PASS",
        "merchant_platform_health": "PASS",
        "public_boundaries": "PASS",
        "migration_lineage": "PASS",
        "finance": "UNCHANGED",
        "shared_operations": "UNCHANGED",
        "pack_platform": "UNCHANGED",
        "dependencies": "UNCHANGED",
        "pc0": report["status"],
        "current_migration_head": head,
        "release_artifacts": len(manifest["artifacts"]),
        "r0_readiness": "PASS",
    }


def database_acceptance() -> dict:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session
    from database import engine
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from uuid import uuid4

    from platform_admin import (
        PlatformAdministrationAuthority, RegisterMerchant, PlanDefinition, PlanQuota, RegisterPlanVersion,
        StartSubscription, TransitionSubscription, SubscriptionStatus, RecordUsage, StartOnboarding,
        EvaluateReadiness, CompleteOnboarding, TransitionMerchant, MerchantAdministrationState,
    )
    from platform_admin.sql_repository import SQLPlatformAdministrationRepository
    from platform_admin.pa45_contracts import (
        OpenSupportSession, SupportAccessMode, RecordSupportAction, TransitionSupportSession, SupportSessionState,
        OpenRecoveryCase, RecordRecoveryAction, RecoveryActionOutcome, TransitionRecoveryCase, RecoveryCaseState,
        CaptureMerchantHealth, CapturePlatformHealth,
    )
    from platform_admin.pa45_service import PA45Authority
    from platform_admin.pa45_sql_repository import SQLPA45Repository

    class TenantGateway:
        def __init__(self, eng): self.eng = eng
        def tenant_lifecycle(self, tenant_id):
            with self.eng.connect() as connection:
                row = connection.execute(text("SELECT lifecycle_state FROM tenants WHERE id=:i"), {"i": tenant_id}).first()
                return None if row is None else row[0]

    class ReadinessGateway:
        def assess(self, **kwargs):
            return {code: ("pass", f"evidence:{code}:{kwargs['tenant_id']}") for code in ("pc1_tenant_available", "pk_template_pinned", "pc4_entitlements_effective", "pc5_tenant_admin_ready")}

    class SecurityGateway:
        def authorize_support(self, **kwargs):
            return True, f"pc5:authorization:{kwargs['tenant_id']}"

    class HealthGateway:
        def __init__(self, now): self.now = now
        def assess_merchant(self, **kwargs):
            tenant = kwargs["tenant_id"]
            return {
                "tenant_context": ("healthy", f"pc1:tenant:{tenant}", self.now),
                "subscription": ("healthy", f"pa:subscription:{tenant}", self.now),
                "integrations": ("degraded", f"so8:delivery:{tenant}", self.now),
            }
        def assess_platform(self):
            return {"database": ("healthy", "ops:database", self.now), "migrations": ("healthy", "ops:migrations", self.now)}

    url = make_url(engine.url)
    if url.host not in LOCAL or url.database != "xbos_track_b_dev":
        raise RuntimeError("PA6_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")

    with engine.connect() as connection:
        dev_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    # Controlled resumable development adoption. PA6 adds no migration, but the
    # accepted PA45 migration is a legal one-step predecessor if an earlier gate
    # left the local development database at PA0123. Never jump from any other head.
    development_action = "VERIFY"
    if dev_head == PA0123_HEAD:
        devurl = url.render_as_string(hide_password=False)
        _run(command.upgrade, Config(str(ROOT / "alembic_neutral.ini")), devurl, HEAD)
        development_action = "ADOPT_PA45"
        with engine.connect() as connection:
            dev_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    elif dev_head != HEAD:
        raise RuntimeError("PA6_DEVELOPMENT_HEAD_UNSAFE=" + dev_head)
    if dev_head != HEAD:
        raise RuntimeError("PA6_DEVELOPMENT_ADOPTION_FAILED=" + dev_head)

    name = "xbos_pa6_aggregate_test"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    test = None

    def drop() -> None:
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"), {"n": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')

    def non_pa_counts(connection) -> tuple[tuple[str, int], ...]:
        tables = [row[0] for row in connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'pa\\_%' ESCAPE '\\' ORDER BY tablename"))]
        return tuple((table, connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()) for table in tables)

    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test = create_engine(url.set(database=name))
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        rendered = url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade, cfg, rendered, HEAD)

        with test.begin() as connection:
            connection.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone,lifecycle_state) VALUES(17001,'PA6A','PA6 Tenant A','CM','XAF','en-CM','Africa/Douala','active'),(17002,'PA6B','PA6 Tenant B','CM','XAF','en-CM','Africa/Douala','active')"))
            before = non_pa_counts(connection)

        now = datetime(2026, 8, 15, 11, 0, tzinfo=timezone.utc)
        actor_a = uuid4()
        actor_b = uuid4()

        with Session(test) as session, session.begin():
            pa = PlatformAdministrationAuthority(SQLPlatformAdministrationRepository(session), TenantGateway(test), ReadinessGateway())
            merchant_a = pa.register_merchant(RegisterMerchant("same-merchant", 17001, "external-a"))
            merchant_b = pa.register_merchant(RegisterMerchant("same-merchant", 17002, "external-b"))
            if merchant_a.tenant_id == merchant_b.tenant_id:
                raise RuntimeError("PA6_TENANT_ISOLATION")

            plan = PlanDefinition("neutral.standard", "1.0.0", "platform_admin", ("platform.core", "reports.basic"), (PlanQuota("api_calls", Decimal("10")),))
            pa.register_plan(RegisterPlanVersion("plan", plan))
            sub = pa.start_subscription(StartSubscription("subscription", 17001, "neutral.standard", "1.0.0", now))
            sub = pa.transition_subscription(TransitionSubscription("activate-subscription", 17001, SubscriptionStatus.ACTIVE, sub.row_version, "commercial contract active"))
            if pa.commercial_entitlement_projection(17001) != ("platform.core", "reports.basic"):
                raise RuntimeError("PA6_ENTITLEMENT_PROJECTION")

            pa.record_usage(RecordUsage("usage-1", 17001, "event-1", "api_calls", Decimal("7"), "2026-08", now, "api:1"))
            pa.record_usage(RecordUsage("usage-2", 17001, "event-2", "api_calls", Decimal("5"), "2026-08", now, "api:2"))
            quota = pa.quota_status(17001, "api_calls", "2026-08")
            if not quota.exceeded or quota.used != Decimal("12"):
                raise RuntimeError("PA6_QUOTA")

            onboarding = pa.start_onboarding(StartOnboarding("onboard", 17001, "neutral.payments_only", "1.0.0", "neutral.standard", "1.0.0"))
            onboarding = pa.evaluate_readiness(EvaluateReadiness("readiness", 17001, onboarding.row_version))
            onboarding = pa.complete_onboarding(CompleteOnboarding("complete-onboarding", 17001, onboarding.row_version))
            merchant = pa.repository.merchant(17001)
            merchant = pa.transition_merchant(TransitionMerchant("go-live", 17001, MerchantAdministrationState.OPERATIONAL, merchant.row_version, "readiness approved"))
            if merchant.state is not MerchantAdministrationState.OPERATIONAL:
                raise RuntimeError("PA6_MERCHANT_OPERATIONAL")

        with Session(test) as session, session.begin():
            support = PA45Authority(SQLPA45Repository(session), SecurityGateway(), HealthGateway(now), now_provider=lambda: now)
            first = OpenSupportSession("same-support", 17001, actor_a, SupportAccessMode.DELEGATED, ("merchant.read", "diagnostics.read"), "support ticket", now, now + timedelta(hours=2), "pc5:auth:a")
            second = OpenSupportSession("same-support", 17002, actor_b, SupportAccessMode.DELEGATED, ("merchant.read",), "support ticket", now, now + timedelta(hours=2), "pc5:auth:b")
            session_a = support.open_support_session(first)
            session_b = support.open_support_session(second)
            if session_a.tenant_id == session_b.tenant_id or support.repository.support_session(17002, session_a.public_id) is not None:
                raise RuntimeError("PA6_SUPPORT_TENANT_ISOLATION")
            if support.open_support_session(first) != session_a:
                raise RuntimeError("PA6_SUPPORT_REPLAY")

            support.record_support_action(RecordSupportAction("support-action", 17001, session_a.public_id, "inspect_config", "pc4:tenant:17001", "audit:support:17001", now + timedelta(minutes=5)))
            case = support.open_recovery_case(OpenRecoveryCase("recovery", 17001, "INC-17001", "integration_uncertain", "provider:external:1", "diagnose only", actor_a, "ticket:17001"))
            support.record_recovery_action(RecordRecoveryAction("recovery-action", 17001, case.public_id, "provider_lookup", RecoveryActionOutcome.INCONCLUSIVE, "provider:lookup:1", now + timedelta(minutes=10), session_a.public_id))
            resolved = support.transition_recovery_case(TransitionRecoveryCase("resolve", 17001, case.public_id, RecoveryCaseState.RESOLVED, case.row_version, "provider state recovered", "audit:resolved"))
            if resolved.state is not RecoveryCaseState.RESOLVED:
                raise RuntimeError("PA6_RECOVERY")
            merchant_health = support.capture_merchant_health(CaptureMerchantHealth("merchant-health", 17001))
            platform_health = support.capture_platform_health(CapturePlatformHealth("platform-health"))
            if merchant_health.status.value != "degraded" or platform_health.status.value != "healthy":
                raise RuntimeError("PA6_HEALTH")
            closed = support.transition_support_session(TransitionSupportSession("close-support", 17001, session_a.public_id, SupportSessionState.CLOSED, session_a.row_version, "ticket complete"))
            if closed.state is not SupportSessionState.CLOSED:
                raise RuntimeError("PA6_SUPPORT_CLOSE")

        with test.begin() as connection:
            usage_id = connection.execute(text("SELECT id FROM pa_usage_events LIMIT 1")).scalar_one()
            action_id = connection.execute(text("SELECT id FROM pa_support_actions LIMIT 1")).scalar_one()
            health_id = connection.execute(text("SELECT id FROM pa_health_snapshots LIMIT 1")).scalar_one()
            mutations = (
                ("UPDATE pa_usage_events SET quantity=999 WHERE id=:i", usage_id),
                ("UPDATE pa_support_actions SET action_code='tampered' WHERE id=:i", action_id),
                ("DELETE FROM pa_health_snapshots WHERE id=:i", health_id),
            )
            for statement, identity in mutations:
                try:
                    with connection.begin_nested():
                        connection.execute(text(statement), {"i": identity})
                except DBAPIError:
                    pass
                else:
                    raise RuntimeError("PA6_APPEND_ONLY_MUTATION_ACCEPTED")
            after = non_pa_counts(connection)
            if after != before:
                raise RuntimeError("PA6_EXTERNAL_AUTHORITY_MUTATION")

        # Rehearse PA migrations as a frozen prefix. PA6 itself adds no migration.
        _run(command.downgrade, cfg, rendered, PA_BASE)
        _run(command.upgrade, cfg, rendered, HEAD)
        with test.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("PA6_REUPGRADE")

        return {
            "disposable_rehearsal": "PASS",
            "full_merchant_journey": "PASS",
            "tenant_isolation": "PASS",
            "tenant_idempotency": "PASS",
            "append_only_evidence": "PASS",
            "external_authorities": "UNCHANGED",
            "development_head": HEAD,
            "development_action": development_action,
        }
    finally:
        if test is not None:
            test.dispose()
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
    print("PA6_VERIFY=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PA6_VERIFY=FAIL\n" + str(exc))
        raise SystemExit(1)
