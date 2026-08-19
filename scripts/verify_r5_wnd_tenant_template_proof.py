from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "7b52093f6fcbe264a56bb1cf673c937488125a3f"
SOURCE_SHA = "b54388395bac540ae5726e8db73ca91e3b334c84ad70f20d02bf502494b8a33a"
SOURCE_SIZE = 6132001
HEAD = "r2_restaurant_menu_fulfillment_043"
DEV = "xbos_track_b_dev"
TEST = "xbos_r5_acceptance"
LOCAL = {"localhost", "127.0.0.1", "::1"}
C = ROOT / "contracts/restaurant/v1"
TEXT = {".cmd", ".json", ".md", ".py", ".sql", ".txt"}

PACK_CODE = "industry.restaurant"
PACK_VERSION = "1.0.0"
COUNTER_TEMPLATE = "restaurant.counter_service"
FULL_TEMPLATE = "restaurant.full_service"
TEMPLATE_VERSION = "1.0.0"
PROOF_TENANT_CODE = "wnd-r5-proof"

R4_EVIDENCE_PATHS = (
    "contracts/restaurant/v1/r0_release_manifest.json",
    "contracts/restaurant/v1/r1_release_manifest.json",
    "contracts/restaurant/v1/r2_release_manifest.json",
    "contracts/restaurant/v1/r3_release_manifest.json",
    "contracts/packs/v1/pk_aggregate_release_manifest.json",
    "contracts/platform/v1/sc41_semantic_classification_hardening.json",
    "contracts/experience/v1/xa_release_manifest.json",
)

CONTROL_TABLES = (
    "financial_events",
    "journal_entries",
    "journal_lines",
    "financial_obligations",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
    "canonical_payment_intents",
    "canonical_payment_attempts",
    "payment_settlements",
    "reconciliation_windows",
    "reconciliation_controls",
    "inventory_movements",
    "sales",
    "orders",
    "atomic_units",
)


def load(name: str):
    return json.loads((C / name).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def r4_evidence_hashes():
    return tuple(sha(ROOT / path) for path in R4_EVIDENCE_PATHS)


def verify_manifest() -> int:
    manifest = load("r5_release_manifest.json")
    if (
        manifest["source_checkpoint"],
        manifest["source_archive_sha256"],
        manifest["source_archive_size"],
    ) != (SOURCE, SOURCE_SHA, SOURCE_SIZE):
        raise RuntimeError("R5_RELEASE_SOURCE")
    if manifest["previous_head"] != HEAD or manifest["accepted_head"] != HEAD or manifest["migration_count"] != 0:
        raise RuntimeError("R5_RELEASE_BOUNDARY")
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        raise RuntimeError("R5_RELEASE_COUNT")
    if len({row["path"] for row in manifest["artifacts"]}) != len(manifest["artifacts"]):
        raise RuntimeError("R5_RELEASE_DUPLICATE_PATH")
    for row in manifest["artifacts"]:
        path = ROOT / row["path"]
        if not path.is_file() or sha(path) != row["sha256"]:
            raise RuntimeError("R5_RELEASE_ARTIFACT=" + row["path"])
    return len(manifest["artifacts"])


def _boundary_proof():
    from core.platform.operating_context import BusinessTimeResolver
    from restaurant.r5 import build_wnd_calendar

    calendar = build_wnd_calendar(501)
    cases = (
        ("2026-08-19T06:59:00+00:00", "night", "2026-08-18"),
        ("2026-08-19T07:00:00+00:00", "day", "2026-08-19"),
        ("2026-08-19T16:59:00+00:00", "day", "2026-08-19"),
        ("2026-08-19T17:00:00+00:00", "night", "2026-08-19"),
    )
    for stamp, shift, business_date in cases:
        result = BusinessTimeResolver.resolve(calendar, datetime.fromisoformat(stamp))
        if result.shift_code != shift or result.business_date.isoformat() != business_date:
            raise RuntimeError("R5_BUSINESS_TIME_BOUNDARY")
    return "PASS"


def static_verify():
    from restaurant.r5 import (
        build_composition_plan,
        build_restaurant_templates,
        build_wnd_profile,
        configuration_keys,
        plan_fingerprint,
    )

    authority = load("r5_wnd_tenant_template_authority.json")
    templates_contract = load("r5_restaurant_templates.json")
    profile_contract = load("r5_wnd_logpom_profile.json")
    pc4 = load("r5_pc4_operating_configuration.json")
    taxonomy = load("r5_taxonomy_overlay_plan.json")
    mapping = load("r5_wnd_migration_mapping_plan.json")
    pk = load("r5_pk_tenant_template_lifecycle.json")
    interfaces = load("r5_public_interfaces.json")
    ready = load("r5_r6_readiness.json")

    if (authority["source_checkpoint"], authority["previous_head"], authority["accepted_head"], authority["migration"]) != (
        SOURCE,
        HEAD,
        HEAD,
        "NONE",
    ):
        raise RuntimeError("R5_HEAD_CONTRACT")
    if authority["database"]["schema_change"] != "NONE" or authority["production"]["changed"]:
        raise RuntimeError("R5_DATABASE_OR_PRODUCTION_SCOPE")
    if authority["proof_tenant"]["code"] != PROOF_TENANT_CODE or authority["proof_tenant"]["production_identity"]:
        raise RuntimeError("R5_PROOF_TENANT_SCOPE")
    if authority["proof_tenant"]["template_pin"] != f"{COUNTER_TEMPLATE}@{TEMPLATE_VERSION}":
        raise RuntimeError("R5_TEMPLATE_PIN")
    if not authority["wnd_specimen_not_standard"]:
        raise RuntimeError("R5_WND_STANDARD_LEAK")

    templates = build_restaurant_templates()
    runtime_codes = {
        templates.counter_service.template_code: templates.counter_service,
        templates.full_service.template_code: templates.full_service,
    }
    if set(runtime_codes) != {COUNTER_TEMPLATE, FULL_TEMPLATE}:
        raise RuntimeError("R5_TEMPLATE_SET")
    for row in templates_contract["templates"]:
        runtime = runtime_codes[row["template_code"]]
        if runtime.version != row["version"] or runtime.owner_code != row["owner_code"]:
            raise RuntimeError("R5_TEMPLATE_IDENTITY")
        if runtime.configuration_defaults != row["configuration_defaults"]:
            raise RuntimeError("R5_TEMPLATE_DEFAULT_DRIFT")
        req = runtime.requirements
        if len(req) != 1 or req[0].pack_code != PACK_CODE or req[0].version != PACK_VERSION or req[0].kind.value != "required":
            raise RuntimeError("R5_TEMPLATE_PACK_REQUIREMENT")
        if not runtime.finance_kernel_required:
            raise RuntimeError("R5_FINANCE_KERNEL_DISABLED")
    if runtime_codes[COUNTER_TEMPLATE].configuration_defaults["restaurant"]["tables"]["enabled"]:
        raise RuntimeError("R5_COUNTER_TABLE_DEFAULT")
    if not runtime_codes[FULL_TEMPLATE].configuration_defaults["restaurant"]["tables"]["enabled"]:
        raise RuntimeError("R5_FULL_SERVICE_CAPABILITY_LOST")

    profile = build_wnd_profile()
    if profile.profile_code != "wnd.logpom" or profile.structure.location_code != "LOGPOM":
        raise RuntimeError("R5_WND_PROFILE_STRUCTURE")
    if profile.template_code != COUNTER_TEMPLATE or profile.template_version != TEMPLATE_VERSION:
        raise RuntimeError("R5_WND_PROFILE_TEMPLATE")
    if profile.production_cutover_authorized:
        raise RuntimeError("R5_CUTOVER_SCOPE")
    if profile.calendar.business_day_boundary.isoformat() != "08:00:00":
        raise RuntimeError("R5_BUSINESS_DAY_BOUNDARY")
    if profile.calendar.payment_shift_cutoff.isoformat() != "18:00:00":
        raise RuntimeError("R5_PAYMENT_CUTOFF")
    if profile.calendar.commission_attribution_basis != "original_order_creator":
        raise RuntimeError("R5_COMMISSION_ATTRIBUTION")
    payment_contract = profile_contract["payment_configuration"]
    for key in ("settlement_methods", "composition_options", "accounting_channels"):
        if profile.payment_configuration[key] != payment_contract[key]:
            raise RuntimeError("R5_PAYMENT_CONFIG_DRIFT=" + key)
    if payment_contract.get("law") != "tenant configuration; not Restaurant or kernel constants":
        raise RuntimeError("R5_PAYMENT_CONFIG_LAW")
    if profile_contract["r6_cutover"] != "NOT_AUTHORIZED":
        raise RuntimeError("R5_R6_CUTOVER_LEAK")

    if len(configuration_keys()) != 11:
        raise RuntimeError("R5_PC4_CONFIGURATION_COUNT")
    if pc4["calendar"]["business_day_boundary"] != "08:00:00":
        raise RuntimeError("R5_PC4_CALENDAR")
    if taxonomy["execution"]["r5"] != "PLAN_AND_PROOF_ONLY" or taxonomy["execution"]["bulk_rewrite"]:
        raise RuntimeError("R5_TAXONOMY_SCOPE")
    if mapping["execution"] != "R6_ONLY" or mapping["production_data_moved_in_r5"]:
        raise RuntimeError("R5_MIGRATION_SCOPE")
    if mapping["finance"]["r5_finance_writer"] or mapping["inventory"]["r5_inventory_writer"]:
        raise RuntimeError("R5_WRITER_SCOPE")
    if pk["direct_pk_table_write"] or pk["direct_pc4_table_write"] or pk["production_wnd_installation"]:
        raise RuntimeError("R5_PK_BOUNDARY")
    if interfaces["http_routes_added"] or interfaces["cross_module_private_access"] != "FORBIDDEN" or interfaces["direct_sql"] != "FORBIDDEN":
        raise RuntimeError("R5_PUBLIC_INTERFACE_BOUNDARY")
    if ready["status"] != "READY_WHEN_R5_SINGLE_GATE_PASS":
        raise RuntimeError("R5_R6_READINESS")

    source = (ROOT / "restaurant/r5/service.py").read_text(encoding="utf-8").lower()
    forbidden = (
        "sql_repository",
        "from database import",
        "session.execute",
        "insert into",
        "update pk_",
        "delete from",
        "update financial_",
        "update inventory_",
    )
    if any(token in source for token in forbidden):
        raise RuntimeError("R5_DIRECT_WRITER_OR_PRIVATE_REPOSITORY")
    if list((ROOT / "alembic_neutral/versions").glob("r5_*")) or list((ROOT / "alembic_neutral/sql").glob("r5_*")):
        raise RuntimeError("R5_MIGRATION_FORBIDDEN")
    plan = build_composition_plan()
    if plan.production_cutover_authorized or plan.database_schema_change != "NONE":
        raise RuntimeError("R5_PLAN_SCOPE")
    if plan_fingerprint() != plan.metadata["plan_fingerprint"] or len(plan_fingerprint()) != 64:
        raise RuntimeError("R5_PLAN_FINGERPRINT")

    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": HEAD,
        "accepted_head": HEAD,
        "migration": "NONE",
        "templates": [COUNTER_TEMPLATE, FULL_TEMPLATE],
        "wnd_template_pin": f"{COUNTER_TEMPLATE}@{TEMPLATE_VERSION}",
        "wnd_proof_tenant": PROOF_TENANT_CODE,
        "business_time": _boundary_proof(),
        "pc4_configuration": "PASS",
        "pk_lifecycle": "PASS",
        "taxonomy_overlay": "PLAN_ONLY",
        "production_cutover": "NONE",
        "r6_readiness": "PASS",
        "release_artifacts": verify_manifest(),
    }


def _counts(connection):
    from sqlalchemy import text

    tables = set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        ).scalars()
    )
    return {
        table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        for table in CONTROL_TABLES
        if table in tables
    }


def _register_r4(session):
    from pack_platform import PackAuthority
    from pack_platform.pk456_service import PK456Authority
    from pack_platform.pk456_sql_repository import SQLPK456Repository
    from pack_platform.sql_repository import SQLPackRepository
    from restaurant.r4 import build_certification_command, build_registration_command

    record = PackAuthority(SQLPackRepository(session)).register(build_registration_command())
    cert = PK456Authority(SQLPK456Repository(session)).certify(
        build_certification_command(r4_evidence_hashes())
    )
    return record, cert


def _compose(session):
    from core.platform.operating_context import OperatingContextAuthority
    from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
    from core.platform.structure import StructuralAuthority
    from core.platform.structure.sql_repository import SQLStructuralRepository
    from pack_platform import PackAuthority
    from pack_platform.pk456_service import PK456Authority
    from pack_platform.pk456_sql_repository import SQLPK456Repository
    from pack_platform.sql_repository import SQLPackRepository
    from restaurant.r5 import (
        activate_restaurant_pack,
        apply_wnd_operating_context,
        build_provision_command,
        plan_and_apply_wnd_template,
        register_templates,
    )

    _register_r4(session)

    structure = StructuralAuthority(SQLStructuralRepository(session)).provision(
        build_provision_command()
    )
    tenant_id = structure.tenant.id

    pk456 = PK456Authority(SQLPK456Repository(session))
    register_templates(pk456)

    active = activate_restaurant_pack(PackAuthority(SQLPackRepository(session)), tenant_id)
    if active.status.value != "active" or active.version != PACK_VERSION:
        raise RuntimeError("R5_PACK_ACTIVATION")

    plan, state = plan_and_apply_wnd_template(pk456, tenant_id)
    if plan.conflicts:
        raise RuntimeError("R5_TEMPLATE_PLAN_CONFLICT=" + ",".join(plan.conflicts))
    if state.template_code != COUNTER_TEMPLATE or state.version != TEMPLATE_VERSION:
        raise RuntimeError("R5_TEMPLATE_APPLICATION")

    calendar = apply_wnd_operating_context(
        OperatingContextAuthority(SQLOperatingContextRepository(session)),
        tenant_id,
        state.effective_configuration,
    )
    return {
        "tenant_id": tenant_id,
        "organization_unit_id": structure.organization_unit.id,
        "legal_entity_id": structure.legal_entity.id,
        "location_id": structure.location.id,
        "template_sha256": state.template_sha256,
        "plan_sha256": plan.plan_sha256,
        "calendar_code": calendar.calendar_code,
    }


def _verify_composition(engine, expected_tenant_id=None):
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from core.platform.operating_context import OperatingContextAuthority
    from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
    from restaurant.r5 import EFFECTIVE_FROM

    with engine.connect() as connection:
        head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if head != HEAD:
            raise RuntimeError("R5_HEAD_CHANGED=" + str(head))

        tenant = connection.execute(
            text("SELECT id,code,name,country_code,currency,locale,timezone FROM tenants WHERE code=:c"),
            {"c": PROOF_TENANT_CODE},
        ).mappings().one_or_none()
        if tenant is None:
            raise RuntimeError("R5_PROOF_TENANT_MISSING")
        tenant_id = tenant["id"]
        if expected_tenant_id is not None and tenant_id != expected_tenant_id:
            raise RuntimeError("R5_PROOF_TENANT_ID_DRIFT")

        location = connection.execute(
            text("SELECT code,name,timezone_name FROM locations WHERE tenant_id=:t AND code='LOGPOM'"),
            {"t": tenant_id},
        ).mappings().one_or_none()
        if location is None or location["name"] != "Logpom" or location["timezone_name"] != "Africa/Douala":
            raise RuntimeError("R5_LOGPOM_STRUCTURE_MISSING")

        installation = connection.execute(
            text("""
                SELECT i.lifecycle_status,v.pack_version
                FROM pk_tenant_pack_installations i
                JOIN pk_packs p ON p.id=i.pack_id
                JOIN pk_pack_versions v ON v.id=i.pack_version_id
                WHERE i.tenant_id=:t AND p.pack_code=:c
            """),
            {"t": tenant_id, "c": PACK_CODE},
        ).mappings().one_or_none()
        if not installation or installation["lifecycle_status"] != "active" or installation["pack_version"] != PACK_VERSION:
            raise RuntimeError("R5_PACK_NOT_ACTIVE")

        binding = connection.execute(
            text("""
                SELECT t.template_code,v.template_version,b.row_version
                FROM pk_tenant_template_bindings b
                JOIN pk_templates t ON t.id=b.template_id
                JOIN pk_template_versions v ON v.id=b.template_version_id
                WHERE b.tenant_id=:tenant
            """),
            {"tenant": tenant_id},
        ).mappings().all()
        if len(binding) != 1 or binding[0]["template_code"] != COUNTER_TEMPLATE or binding[0]["template_version"] != TEMPLATE_VERSION:
            raise RuntimeError("R5_TEMPLATE_BINDING")

        templates = set(
            connection.execute(
                text("""
                    SELECT t.template_code
                    FROM pk_templates t JOIN pk_template_versions v ON v.template_id=t.id
                    WHERE v.template_version=:v AND t.template_code IN (:counter,:full)
                """),
                {"v": TEMPLATE_VERSION, "counter": COUNTER_TEMPLATE, "full": FULL_TEMPLATE},
            ).scalars()
        )
        if templates != {COUNTER_TEMPLATE, FULL_TEMPLATE}:
            raise RuntimeError("R5_TEMPLATE_REGISTRY")

        full_binding = connection.execute(
            text("""
                SELECT count(*)
                FROM pk_tenant_template_bindings b
                JOIN pk_templates t ON t.id=b.template_id
                WHERE b.tenant_id=:tenant AND t.template_code=:code
            """),
            {"tenant": tenant_id, "code": FULL_TEMPLATE},
        ).scalar_one()
        if full_binding:
            raise RuntimeError("R5_FULL_SERVICE_TEMPLATE_SHOULD_NOT_BE_WND_BINDING")

        overrides = {
            row["override_path"]: row["override_json"]
            for row in connection.execute(
                text("""
                    SELECT o.override_path,o.override_json
                    FROM pk_tenant_template_overrides o
                    JOIN pk_tenant_template_bindings b ON b.id=o.binding_id
                    WHERE b.tenant_id=:tenant
                    ORDER BY o.override_path
                """),
                {"tenant": tenant_id},
            ).mappings()
        }
        expected_overrides = {
            "restaurant.commissions.enabled": True,
            "restaurant.service_modes.enabled": ["dine_in", "takeaway", "delivery"],
            "restaurant.tips.enabled": False,
        }
        if overrides != expected_overrides:
            raise RuntimeError("R5_TEMPLATE_OVERRIDES=" + json.dumps(overrides, sort_keys=True))

        calendar = connection.execute(
            text("""
                SELECT id,business_day_boundary,timezone_name
                FROM business_calendars
                WHERE tenant_id=:t AND calendar_code='wnd.operations' AND calendar_version=1
            """),
            {"t": tenant_id},
        ).mappings().one_or_none()
        if not calendar or calendar["business_day_boundary"].isoformat() != "08:00:00" or calendar["timezone_name"] != "Africa/Douala":
            raise RuntimeError("R5_CALENDAR_MISSING")
        shifts = {
            row["shift_code"]: (row["starts_at"].isoformat(), row["ends_at"].isoformat())
            for row in connection.execute(
                text("SELECT shift_code,starts_at,ends_at FROM shift_definitions WHERE business_calendar_id=:i"),
                {"i": calendar["id"]},
            ).mappings()
        }
        if shifts != {"day": ("08:00:00", "18:00:00"), "night": ("18:00:00", "08:00:00")}:
            raise RuntimeError("R5_SHIFT_DEFINITIONS")

        if connection.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'r5_%'")
        ).scalar_one():
            raise RuntimeError("R5_TABLES_FORBIDDEN")

    with Session(engine) as session:
        operating = OperatingContextAuthority(SQLOperatingContextRepository(session))
        at = datetime(2026, 8, 20, tzinfo=timezone.utc)
        resolved = {
            key: operating.resolve(tenant_id=tenant_id, key=key, as_of=at).value
            for key in (
                "restaurant.tables.enabled",
                "restaurant.reservations.enabled",
                "restaurant.fulfillment.course_firing.enabled",
                "restaurant.fulfillment.output_delivery.enabled",
                "restaurant.fulfillment.station_routing.enabled",
                "restaurant.service_modes.enabled",
                "restaurant.tips.enabled",
                "restaurant.commissions.enabled",
                "wnd.payment_shift.cutoff_local_time",
                "wnd.payments.enabled_methods",
                "wnd.commission.attribution_basis",
            )
        }

    if resolved["restaurant.tables.enabled"] is not False:
        raise RuntimeError("R5_PC4_TABLES")
    if resolved["restaurant.reservations.enabled"] is not False:
        raise RuntimeError("R5_PC4_RESERVATIONS")
    if resolved["restaurant.service_modes.enabled"] != ["dine_in", "takeaway", "delivery"]:
        raise RuntimeError("R5_PC4_SERVICE_MODES")
    if resolved["restaurant.tips.enabled"] is not False or resolved["restaurant.commissions.enabled"] is not True:
        raise RuntimeError("R5_PC4_TIPS_COMMISSIONS")
    if resolved["wnd.payment_shift.cutoff_local_time"].isoformat() != "18:00:00":
        raise RuntimeError("R5_PC4_PAYMENT_CUTOFF")
    if resolved["wnd.commission.attribution_basis"] != "original_order_creator":
        raise RuntimeError("R5_PC4_COMMISSION_ATTRIBUTION")
    if resolved["wnd.payments.enabled_methods"]["settlement_methods"] != ["cash", "mtn", "orange"]:
        raise RuntimeError("R5_PC4_PAYMENT_METHODS")

    return {
        "tenant_id": tenant_id,
        "pack": "ACTIVE",
        "template": f"{COUNTER_TEMPLATE}@{TEMPLATE_VERSION}",
        "calendar": "08:00-08:00",
        "payment_cutoff": "18:00",
        "commission_attribution": "original_order_creator",
    }


def acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine as app

    url = make_url(app.url)
    if url.host not in LOCAL or url.database != DEV:
        raise RuntimeError("R5_REFUSING_DATABASE=" + str(url))

    def eng(database, auto=False):
        return create_engine(
            url.set(database=database),
            pool_pre_ping=True,
            isolation_level="AUTOCOMMIT" if auto else None,
        )

    def run(operation, cfg, target_url, target):
        old = {key: os.environ.get(key) for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
        cfg.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))
        os.environ.update(DATABASE_URL=target_url, MIGRATION_DATABASE_URL=target_url)
        try:
            operation(cfg, target)
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    admin = eng("postgres", True)
    disposable = None

    def drop():
        with admin.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),
                {"n": TEST},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST}"')

    try:
        drop()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')

        disposable = eng(TEST)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        target_url = url.set(database=TEST).render_as_string(hide_password=False)
        run(command.upgrade, cfg, target_url, HEAD)

        with disposable.connect() as connection:
            before = _counts(connection)

        with Session(disposable, expire_on_commit=False) as session, session.begin():
            state = _compose(session)

        verified = _verify_composition(disposable, state["tenant_id"])

        with disposable.connect() as connection:
            after = _counts(connection)
            if after != before:
                delta = {key: (before.get(key), after.get(key)) for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}
                raise RuntimeError("R5_CONTROL_TABLES_CHANGED=" + json.dumps(delta, sort_keys=True))
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                raise RuntimeError("R5_DISPOSABLE_HEAD_CHANGED")

        with Session(disposable, expire_on_commit=False) as session, session.begin():
            replay = _compose(session)
        if replay["tenant_id"] != state["tenant_id"] or replay["plan_sha256"] != state["plan_sha256"]:
            raise RuntimeError("R5_COMPOSITION_REPLAY_CHANGED")

        verified_replay = _verify_composition(disposable, state["tenant_id"])
        if verified_replay != verified:
            raise RuntimeError("R5_REPLAY_VERIFICATION_DRIFT")

        return {
            "disposable_composition": "PASS",
            "idempotent_replay": "PASS",
            "schema_head": HEAD,
            "control_tables": "UNCHANGED",
            **verified,
        }
    finally:
        if disposable is not None:
            disposable.dispose()
        drop()
        admin.dispose()


def adopt_development():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine

    url = make_url(engine.url)
    if url.host not in LOCAL or url.database != DEV:
        raise RuntimeError("R5_REFUSING_DATABASE=" + str(url))

    with engine.connect() as connection:
        if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
            raise RuntimeError("R5_DEVELOPMENT_HEAD")
        before = _counts(connection)

    with Session(engine, expire_on_commit=False) as session, session.begin():
        state = _compose(session)

    verified = _verify_composition(engine, state["tenant_id"])

    with engine.connect() as connection:
        after = _counts(connection)
        if after != before:
            delta = {key: (before.get(key), after.get(key)) for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}
            raise RuntimeError("R5_DEVELOPMENT_CONTROL_TABLES_CHANGED=" + json.dumps(delta, sort_keys=True))
        if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
            raise RuntimeError("R5_DEVELOPMENT_HEAD_CHANGED")

    print("R5_DEVELOPMENT_DATABASE=" + DEV)
    print("R5_DEVELOPMENT_HEAD=" + HEAD)
    print("R5_DEVELOPMENT_PROOF_TENANT_ID=" + str(verified["tenant_id"]))
    print("R5_DEVELOPMENT_PROOF_TENANT_CODE=" + PROOF_TENANT_CODE)
    print("R5_DEVELOPMENT_PACK_ACTIVE=PASS")
    print("R5_DEVELOPMENT_TEMPLATE_PIN=" + verified["template"])
    print("R5_DEVELOPMENT_PC4_CALENDAR=PASS")
    print("R5_DEVELOPMENT_CONTROL_TABLES_UNCHANGED=PASS")
    print("R5_DEVELOPMENT_WND_PRODUCTION=UNCHANGED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--adopt-development", action="store_true")
    args = parser.parse_args()
    try:
        result = static_verify()
        if args.acceptance:
            result["database"] = acceptance()
        print(json.dumps(result, indent=2, sort_keys=True))
        print("R5_VERIFY=PASS")
        if args.adopt_development:
            adopt_development()
    except Exception as exc:
        print("R5_VERIFY=FAIL")
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
