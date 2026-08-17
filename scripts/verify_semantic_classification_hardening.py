#!/usr/bin/env python3
"""Verify Pre-R0 semantic classification hardening and controlled PostgreSQL proof."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "11e7c902475560122794790d3a080a29d65cc972"
SOURCE_ARCHIVE_SHA256 = "0529c7360d1b8c3d77aa82d41c79b1e9df4e037798fd7effab76ad29befc7c73"
SOURCE_ARCHIVE_SIZE = 5937670
PREVIOUS = "pa45_support_recovery_health_040"
HEAD = "semantic_classification_hardening_041"
DEV = "xbos_track_b_dev"
TEST = "xbos_semantic_classification_hardening_test"
LOCAL = {"localhost", "127.0.0.1", "::1"}
CONTRACTS = ROOT / "contracts/platform/v1"
NEW_TABLES = {
    "semantic_classification_commands",
    "semantic_taxonomy_nodes",
    "semantic_taxonomy_placements",
    "tenant_taxonomy_overlays",
    "semantic_classification_governance",
}
TEXT_SUFFIXES = {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


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
                raise RuntimeError("SEMANTIC_HARDENING_DUPLICATE_MIGRATION=" + revision)
            parent = values.get("down_revision")
            revisions[revision] = parent if isinstance(parent, str) else None
    parents = {value for value in revisions.values() if value}
    heads = sorted(set(revisions) - parents)
    if heads != [HEAD]:
        raise RuntimeError("SEMANTIC_HARDENING_MIGRATION_HEAD=" + ",".join(heads))
    lineage: list[str] = []
    current: str | None = HEAD
    while current:
        if current in lineage or current not in revisions:
            raise RuntimeError("SEMANTIC_HARDENING_MIGRATION_LINEAGE=" + str(current))
        lineage.append(current)
        current = revisions[current]
    return HEAD, list(reversed(lineage))


def _development_action(head: str) -> str:
    if head == PREVIOUS:
        return "UPGRADE"
    if head == HEAD:
        return "VERIFY_IN_PLACE"
    raise RuntimeError("SEMANTIC_HARDENING_DEVELOPMENT_HEAD=" + head)


def _verify_release_manifest() -> int:
    manifest = _json(CONTRACTS / "sc41_release_manifest.json")
    seen = set()
    for item in manifest["artifacts"]:
        relative = item["path"]
        if relative in seen:
            raise RuntimeError("SEMANTIC_HARDENING_DUPLICATE_RELEASE_ARTIFACT=" + relative)
        seen.add(relative)
        path = ROOT / relative
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError("SEMANTIC_HARDENING_RELEASE_MISMATCH=" + relative)
    return len(seen)


def static_verify() -> dict:
    from core.platform.architecture_contract import validate_pc0

    authority = _json(CONTRACTS / "sc41_semantic_classification_hardening.json")
    registry = _json(CONTRACTS / "sc41_global_taxonomy_registry.json")
    interfaces = _json(CONTRACTS / "sc41_public_interfaces.json")
    targets = _json(CONTRACTS / "sc41_classification_target_contract.json")

    if (authority["source_checkpoint"], authority["source_archive_sha256"], authority["source_archive_size"]) != (SOURCE, SOURCE_ARCHIVE_SHA256, SOURCE_ARCHIVE_SIZE):
        raise RuntimeError("SEMANTIC_HARDENING_SOURCE_BOUNDARY")
    if (authority["previous_head"], authority["accepted_head"], authority["migration_count"]) != (PREVIOUS, HEAD, 1):
        raise RuntimeError("SEMANTIC_HARDENING_RELEASE_BOUNDARY")
    if set(authority["new_tables"]) != NEW_TABLES:
        raise RuntimeError("SEMANTIC_HARDENING_TABLE_SCOPE")
    if any(value is not False for value in authority["frozen_compatibility"].values()):
        raise RuntimeError("SEMANTIC_HARDENING_FROZEN_SCOPE_MUTATION")
    if authority["frozen_compatibility"].get("finance_authority_implementation_modified", False):
        raise RuntimeError("SEMANTIC_HARDENING_FINANCE_SCOPE")
    integrity = authority.get("release_integrity", {})
    if integrity.get("cumulative_release_metadata_refreshed") is not True:
        raise RuntimeError("SEMANTIC_HARDENING_RELEASE_METADATA_REFRESH")
    if integrity.get("historical_pc1_pc5_release_manifests_rewritten") is not False:
        raise RuntimeError("SEMANTIC_HARDENING_HISTORICAL_RELEASE_REWRITE")

    systems = registry["systems"]
    if registry["taxonomy_system_count"] != 40 or len(systems) != 40:
        raise RuntimeError("SEMANTIC_HARDENING_TAXONOMY_SYSTEM_COUNT")
    codes = [item["system_code"] for item in systems]
    if len(set(codes)) != 40 or any(not item["depth_1_domains"] for item in systems):
        raise RuntimeError("SEMANTIC_HARDENING_TAXONOMY_REGISTRY")
    required = {"commerce", "finance", "operations", "party", "industry", "tax", "security_access", "measurement_units", "standards_reference"}
    if not required.issubset(codes):
        raise RuntimeError("SEMANTIC_HARDENING_TAXONOMY_COVERAGE")
    if registry["universal_tree"] is not False or "unbounded" not in registry["depth_model"]:
        raise RuntimeError("SEMANTIC_HARDENING_HIERARCHY_LAW")

    if set(interfaces["read_models"]) != {"hierarchy", "object_classifications", "matrix", "graph", "health"}:
        raise RuntimeError("SEMANTIC_HARDENING_READ_MODELS")
    target_count = len(targets["tenant_contextual_targets"]) + len(targets["native_global_semantic_reference_targets"])
    if target_count < 7 or "arbitrary dynamic table lookup is forbidden" not in targets["law"]:
        raise RuntimeError("SEMANTIC_HARDENING_TARGET_GOVERNANCE")
    if "fake platform tenant" not in targets["assignment_context"]:
        raise RuntimeError("SEMANTIC_HARDENING_GLOBAL_TARGET_SCOPE")

    wrapper = (ROOT / "alembic_neutral/versions/semantic_classification_hardening_041.py").read_text(encoding="utf-8")
    if f'revision = "{HEAD}"' not in wrapper or f'down_revision = "{PREVIOUS}"' not in wrapper:
        raise RuntimeError("SEMANTIC_HARDENING_MIGRATION_WRAPPER")
    up = (ROOT / "alembic_neutral/sql/semantic_classification_hardening_up.sql").read_text(encoding="utf-8")
    for table in NEW_TABLES:
        if f"CREATE TABLE public.{table}" not in up:
            raise RuntimeError("SEMANTIC_HARDENING_TABLE_MISSING=" + table)
    forbidden = (
        "ALTER TABLE public.taxonomy_nodes",
        "ALTER TABLE public.atomic_units",
        "ALTER TABLE public.atomic_unit_taxonomy",
        "ALTER TABLE public.semantic_commands",
        "UPDATE public.financial_",
        "DELETE FROM public.financial_",
        "INSERT INTO public.financial_",
    )
    if any(token in up for token in forbidden):
        raise RuntimeError("SEMANTIC_HARDENING_FORBIDDEN_FROZEN_MUTATION")
    required_sql = (
        "NULLS NOT DISTINCT",
        "overlapping_taxonomy_placement",
        "taxonomy_cycle",
        "effective_taxonomy_cycle",
        "cross_tenant_taxonomy_overlay_forbidden",
        "classification_node_concept_mismatch",
        "semantic_taxonomy_placement_is_historical",
        "semantic_classification_governance_is_historical",
    )
    if not all(token in up for token in required_sql):
        raise RuntimeError("SEMANTIC_HARDENING_GOVERNANCE_GUARD")

    repository = (ROOT / "core/platform/semantics/classification_hardening/sql_repository.py").read_text(encoding="utf-8")
    joined_system_lock = "LEFT JOIN semantic_namespaces ns ON ns.id=s.namespace_id WHERE s.system_code=lower(btrim(:code)) FOR UPDATE OF s"
    if joined_system_lock not in repository:
        raise RuntimeError("SEMANTIC_HARDENING_TAXONOMY_SYSTEM_LOCK_SCOPE")
    if "def _semantic_date" not in repository or "CAST(:on AS date)" in repository:
        raise RuntimeError("SEMANTIC_HARDENING_SEMANTIC_DATE_BRIDGE")

    _, lineage = _migration_lineage()
    prior_index = lineage.index(PREVIOUS)
    if lineage[prior_index + 1] != HEAD:
        raise RuntimeError("SEMANTIC_HARDENING_NOT_DIRECT_DESCENDANT")

    for relative, expected in authority["dependency_fingerprints"].items():
        path = ROOT / relative
        if not path.is_file() or _canonical_sha(path) != expected:
            raise RuntimeError("SEMANTIC_HARDENING_DEPENDENCY_CHANGED=" + relative)

    # These exact frozen implementation files must remain untouched. New behavior is additive.
    for relative in (
        "core/platform/semantics/contracts.py",
        "core/platform/semantics/service.py",
        "core/platform/semantics/sql_repository.py",
        "shared_operations/so1/service.py",
        "shared_operations/so1/sql_repository.py",
    ):
        if relative not in authority["dependency_fingerprints"]:
            raise RuntimeError("SEMANTIC_HARDENING_FROZEN_PROOF_MISSING=" + relative)

    pc0 = validate_pc0(ROOT, validate_release=False)
    release_count = _verify_release_manifest()
    return {
        "status": "PASS",
        "source_checkpoint": SOURCE[:7],
        "previous_head": PREVIOUS,
        "accepted_head": HEAD,
        "taxonomy_systems": 40,
        "read_models": "PASS",
        "global_scope": "PASS",
        "history": "PASS",
        "tenant_overlays": "PASS",
        "target_governance": "PASS",
        "frozen_dependencies": "UNCHANGED",
        "pc0": pc0["status"],
        "release_artifacts": release_count,
    }


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


def _schema_tables(connection) -> set[str]:
    return set(connection.execute(__import__("sqlalchemy").text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())


def _counts(connection, tables: set[str]) -> dict[str, int]:
    from sqlalchemy import text
    return {table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() for table in sorted(tables)}


def _verify_schema(connection) -> None:
    from sqlalchemy import text
    head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if head != HEAD:
        raise RuntimeError("SEMANTIC_HARDENING_SCHEMA_HEAD=" + str(head))
    tables = _schema_tables(connection)
    missing = NEW_TABLES - tables
    if missing:
        raise RuntimeError("SEMANTIC_HARDENING_TABLES_MISSING=" + ",".join(sorted(missing)))
    constraints = set(connection.execute(text("""SELECT conname FROM pg_constraint
        WHERE connamespace='public'::regnamespace AND conrelid IN (
            'semantic_classification_commands'::regclass,
            'semantic_taxonomy_nodes'::regclass,
            'semantic_taxonomy_placements'::regclass,
            'tenant_taxonomy_overlays'::regclass,
            'semantic_classification_governance'::regclass)""")).scalars())
    expected_constraints = {
        "fk_semantic_taxonomy_nodes_system",
        "fk_semantic_taxonomy_nodes_concept",
        "fk_semantic_taxonomy_placement_parent",
        "fk_tenant_taxonomy_overlays_node",
        "fk_semantic_classification_governance_assignment",
        "fk_semantic_classification_governance_node",
    }
    if not expected_constraints.issubset(constraints):
        raise RuntimeError("SEMANTIC_HARDENING_CONSTRAINTS_MISSING=" + ",".join(sorted(expected_constraints - constraints)))
    triggers = set(connection.execute(text("""SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN (
        'semantic_taxonomy_nodes'::regclass,
        'semantic_taxonomy_placements'::regclass,
        'tenant_taxonomy_overlays'::regclass,
        'semantic_classification_governance'::regclass)""")).scalars())
    expected_triggers = {
        "trg_sc41_semantic_taxonomy_node_scope",
        "trg_sc41_semantic_taxonomy_placement_validate",
        "trg_sc41_semantic_taxonomy_placement_effective_cycle",
        "trg_sc41_semantic_taxonomy_placement_protect",
        "trg_sc41_tenant_taxonomy_overlay_validate",
        "trg_sc41_tenant_taxonomy_overlay_effective_cycle",
        "trg_sc41_tenant_taxonomy_overlay_protect",
        "trg_sc41_semantic_classification_governance_validate",
        "trg_sc41_semantic_classification_governance_protect",
    }
    if not expected_triggers.issubset(triggers):
        raise RuntimeError("SEMANTIC_HARDENING_TRIGGERS_MISSING=" + ",".join(sorted(expected_triggers - triggers)))


def database_acceptance() -> dict:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from database import engine as application_engine
    from core.platform.semantics import (
        CreateConcept,
        CreateNamespace,
        CreateSemanticVersion,
        NamespaceScope,
        SQLSemanticRepository,
        SemanticAuthority,
        SemanticAuthorityError,
    )
    from core.platform.semantics.classification_hardening import (
        AssignSemanticClassification,
        AssignmentMode,
        ClassificationTargetRegistry,
        CreateTaxonomyNode,
        CreateTaxonomySystem,
        ReparentTaxonomyNode,
        SQLSemanticClassificationRepository,
        SemanticClassificationAuthority,
        SemanticSource,
        SetTenantTaxonomyOverlay,
        TargetScope,
        TargetTypeDefinition,
    )

    url = make_url(application_engine.url)
    if url.host not in LOCAL:
        raise RuntimeError("SEMANTIC_HARDENING_REFUSING_NON_LOCAL_DATABASE")
    if url.database != DEV:
        raise RuntimeError("SEMANTIC_HARDENING_DEVELOPMENT_DATABASE=" + str(url.database))

    def engine_for(database: str, autocommit: bool = False):
        options = {"pool_pre_ping": True}
        if autocommit:
            options["isolation_level"] = "AUTOCOMMIT"
        return create_engine(url.set(database=database), **options)

    admin = engine_for("postgres", True)
    test_engine = None

    def drop_test() -> None:
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": TEST})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST}"')

    try:
        drop_test()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')
        test_engine = engine_for(TEST)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        test_url = url.set(database=TEST).render_as_string(hide_password=False)

        _run(command.upgrade, cfg, test_url, PREVIOUS)
        with test_engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != PREVIOUS:
                raise RuntimeError("SEMANTIC_HARDENING_PREDECESSOR_REPLAY")
            if NEW_TABLES & _schema_tables(connection):
                raise RuntimeError("SEMANTIC_HARDENING_PREDECESSOR_CONTAMINATION")
        _run(command.upgrade, cfg, test_url, HEAD)
        with test_engine.connect() as connection:
            _verify_schema(connection)

        tenant_a, tenant_b = 18401, 18402
        with test_engine.begin() as connection:
            connection.execute(text("""INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone,lifecycle_state)
                VALUES(:a,'SC41A','Semantic Tenant A','CM','XAF','fr-CM','Africa/Douala','active'),
                      (:b,'SC41B','Semantic Tenant B','US','USD','en-US','America/Chicago','active')"""), {"a": tenant_a, "b": tenant_b})

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        move_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
        before_move = datetime(2026, 12, 31, 12, tzinfo=timezone.utc)
        after_move = datetime(2027, 1, 2, 12, tzinfo=timezone.utc)
        restaurant_source = "restaurant.core@1.0.0"

        with Session(test_engine, expire_on_commit=False) as session, session.begin():
            pc3 = SemanticAuthority(SQLSemanticRepository(session))
            pc3.create_namespace(CreateNamespace("sc41-kernel-ns", "sc41.kernel", NamespaceScope.KERNEL, "sc41"))
            pc3.create_namespace(CreateNamespace("sc41-pack-ns", "sc41.restaurant", NamespaceScope.PACK, "pack:restaurant"))
            pc3.create_namespace(CreateNamespace("sc41-tenant-a-ns", f"sc41.tenant.{tenant_a}", NamespaceScope.TENANT, f"tenant:{tenant_a}", tenant_a))

            def concept(namespace: str, owner: str, code: str, label: str):
                item = pc3.create_concept(CreateConcept("concept-" + code, namespace, owner, code))
                pc3.create_version(CreateSemanticVersion("version-" + code, namespace, owner, code, 1, date(2026, 1, 1), None, label, "SC41 acceptance concept: " + label))
                return item

            for code, label in (
                ("beverage", "Beverage"),
                ("beer", "Beer"),
                ("wine", "Wine"),
                ("alcoholic_beverages", "Alcoholic Beverages"),
                ("prepared_food", "Prepared Food"),
                ("payment_settlement", "Payment Settlement"),
            ):
                concept("sc41.kernel", "sc41", code, label)
            concept("sc41.restaurant", "pack:restaurant", "bar_beer", "Bar Beer")
            concept(f"sc41.tenant.{tenant_a}", f"tenant:{tenant_a}", "bamileke_specialties", "Bamileke Specialties")

            registry = ClassificationTargetRegistry()
            def atomic_validator(tenant_id: int, target_key: str) -> bool:
                try:
                    value = UUID(target_key)
                except ValueError:
                    return False
                return session.execute(text("SELECT 1 FROM atomic_units WHERE tenant_id=:tenant AND public_id=:public"), {"tenant": tenant_id, "public": value}).scalar_one_or_none() == 1
            registry.register(TargetTypeDefinition("atomic_unit", "SO1", TargetScope.TENANT, "uuid"), atomic_validator)
            semantic = SemanticClassificationAuthority(SQLSemanticClassificationRepository(session), registry)

            commerce = semantic.create_taxonomy_system(CreateTaxonomySystem("system-commerce", "commerce", "sc41", "sc41.kernel"))
            finance = semantic.create_taxonomy_system(CreateTaxonomySystem("system-finance", "finance", "sc41", "sc41.kernel"))
            if commerce.tenant_id is not None or finance.tenant_id is not None:
                raise RuntimeError("SEMANTIC_HARDENING_GLOBAL_SYSTEM_SCOPE")

            beverage, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-beverage", "commerce", "sc41.kernel:beverage", "beverage", start, source_key="xbos.global"))
            beer, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-beer", "commerce", "sc41.kernel:beer", "beer", start, parent_node_public_id=beverage.public_id, sort_order=10, source_key="xbos.global"))
            wine, wine_p1 = semantic.create_taxonomy_node(CreateTaxonomyNode("node-wine", "commerce", "sc41.kernel:wine", "wine", start, parent_node_public_id=beverage.public_id, sort_order=20, source_key="xbos.global"))
            alcoholic, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-alcohol", "commerce", "sc41.kernel:alcoholic_beverages", "alcoholic_beverages", start, source_key="xbos.global"))
            prepared, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-prepared", "commerce", "sc41.kernel:prepared_food", "prepared_food", start, source_key="xbos.global"))
            pack_beer, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-pack-beer", "commerce", "sc41.restaurant:bar_beer", "restaurant_bar_beer", start, parent_node_public_id=beer.public_id, source_type=SemanticSource.PACK, source_key=restaurant_source, provenance={"pack": "restaurant", "version": "1.0.0"}))
            tenant_special, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-tenant-special", "commerce", f"sc41.tenant.{tenant_a}:bamileke_specialties", "bamileke_specialties", start, tenant_id=tenant_a, parent_node_public_id=prepared.public_id, source_type=SemanticSource.TENANT, source_key=f"tenant:{tenant_a}"))
            settlement, _ = semantic.create_taxonomy_node(CreateTaxonomyNode("node-settlement", "finance", "sc41.kernel:payment_settlement", "payment_settlement", start, source_key="xbos.global"))

            unit_a, unit_b = uuid4(), uuid4()
            session.execute(text("""INSERT INTO atomic_units(tenant_id,name,sku,is_active,public_id)
                VALUES(:a,'Heineken 33cl','SC41-H-A',true,:ua),(:b,'Provider Settlement Unit','SC41-P-B',true,:ub)"""),
                {"a": tenant_a, "b": tenant_b, "ua": unit_a, "ub": unit_b})

            first = semantic.assign(AssignSemanticClassification(
                "same-classification-key", tenant_a, "atomic_unit", str(unit_a), "sc41.kernel:beer", start,
                beer.public_id, AssignmentMode.EXPLICIT, SemanticSource.TEMPLATE, restaurant_source,
                {"template": "restaurant.core", "version": "1.0.0"},
            ))
            replay = semantic.assign(AssignSemanticClassification(
                "same-classification-key", tenant_a, "atomic_unit", str(unit_a), "sc41.kernel:beer", start,
                beer.public_id, AssignmentMode.EXPLICIT, SemanticSource.TEMPLATE, restaurant_source,
                {"template": "restaurant.core", "version": "1.0.0"},
            ))
            if replay.assignment_id != first.assignment_id:
                raise RuntimeError("SEMANTIC_HARDENING_ASSIGNMENT_REPLAY")
            # The same caller key is legal in another tenant: idempotency is tenant-qualified.
            second = semantic.assign(AssignSemanticClassification(
                "same-classification-key", tenant_b, "atomic_unit", str(unit_b), "sc41.kernel:payment_settlement", start,
                settlement.public_id, AssignmentMode.EXPLICIT, SemanticSource.KERNEL, "xbos.global", {"profile": "payments_only"},
            ))
            if second.tenant_id == first.tenant_id:
                raise RuntimeError("SEMANTIC_HARDENING_TENANT_COMMAND_SCOPE")
            if semantic.classifications(
                tenant_id=tenant_a, target_type="atomic_unit", target_key=str(unit_a),
                effective_at=before_move, active_sources=(),
            ):
                raise RuntimeError("SEMANTIC_HARDENING_INACTIVE_TEMPLATE_CLASSIFICATION_LEAK")

            try:
                semantic.assign(AssignSemanticClassification(
                    "same-classification-key", tenant_a, "atomic_unit", str(unit_a), "sc41.kernel:wine", start,
                    wine.public_id, AssignmentMode.EXPLICIT, SemanticSource.TENANT, f"tenant:{tenant_a}", {},
                ))
            except SemanticAuthorityError as exc:
                if exc.code != "conflicting_semantic_classification_command_replay":
                    raise
            else:
                raise RuntimeError("SEMANTIC_HARDENING_CONFLICTING_REPLAY_ACCEPTED")

            semantic.set_tenant_overlay(SetTenantTaxonomyOverlay(
                "overlay-beer", tenant_a, beer.public_id, None, start,
                local_label="Bières", local_sort_order=5, source_type=SemanticSource.TENANT,
                source_key=f"tenant:{tenant_a}", provenance={"reason": "merchant terminology"},
            ))

            tree_a = semantic.hierarchy(system_code="commerce", effective_at=before_move, tenant_id=tenant_a, active_sources=(restaurant_source,))
            tree_b = semantic.hierarchy(system_code="commerce", effective_at=before_move, tenant_id=tenant_b, active_sources=())
            a_by_code = {item.node_code: item for item in tree_a}
            b_by_code = {item.node_code: item for item in tree_b}
            if a_by_code["beer"].label != "Bières" or b_by_code["beer"].label != "Beer":
                raise RuntimeError("SEMANTIC_HARDENING_TENANT_OVERLAY")
            if "restaurant_bar_beer" not in a_by_code or "restaurant_bar_beer" in b_by_code:
                raise RuntimeError("SEMANTIC_HARDENING_PACK_SOURCE_COMPOSITION")
            if "bamileke_specialties" not in a_by_code or "bamileke_specialties" in b_by_code:
                raise RuntimeError("SEMANTIC_HARDENING_TENANT_EXTENSION_ISOLATION")

            # A tenant may explicitly re-parent an inherited node to root; NULL alone means no override.
            semantic.set_tenant_overlay(SetTenantTaxonomyOverlay(
                "overlay-root-parent", tenant_b, beer.public_id, None, start.replace(day=2),
                parent_override_public_id=None, has_parent_override=True,
                source_type=SemanticSource.TENANT, source_key=f"tenant:{tenant_b}",
                provenance={"reason": "root projection proof"},
            ))
            tree_b_root = {item.node_code: item for item in semantic.hierarchy(
                system_code="commerce", effective_at=before_move, tenant_id=tenant_b, active_sources=()
            )}
            if tree_b_root["beer"].path != ("Beer",):
                raise RuntimeError("SEMANTIC_HARDENING_ROOT_PARENT_OVERRIDE")

            try:
                semantic.set_tenant_overlay(SetTenantTaxonomyOverlay(
                    "overlay-cross-tenant", tenant_b, tenant_special.public_id, None, start,
                    local_label="Leak", source_type=SemanticSource.TENANT, source_key=f"tenant:{tenant_b}",
                ))
            except SemanticAuthorityError as exc:
                if exc.code != "taxonomy_node_not_visible_to_tenant":
                    raise
            else:
                raise RuntimeError("SEMANTIC_HARDENING_CROSS_TENANT_OVERLAY_ACCEPTED")

            # Effective tenant overlays may not create a latent cycle, even through a pack node.
            try:
                with session.begin_nested():
                    semantic.set_tenant_overlay(SetTenantTaxonomyOverlay(
                        "overlay-cycle", tenant_a, beer.public_id, 1, start.replace(day=2),
                        parent_override_public_id=pack_beer.public_id, has_parent_override=True, source_type=SemanticSource.TENANT,
                        source_key=f"tenant:{tenant_a}", provenance={"test": "cycle_guard"},
                    ))
            except SemanticAuthorityError:
                pass
            else:
                raise RuntimeError("SEMANTIC_HARDENING_EFFECTIVE_OVERLAY_CYCLE_ACCEPTED")

            moved = semantic.reparent_taxonomy_node(ReparentTaxonomyNode(
                "move-wine", wine.public_id, wine_p1.placement_version, move_at,
                alcoholic.public_id, sort_order=10, source_key="xbos.global",
            ))
            if moved.placement_version != 2:
                raise RuntimeError("SEMANTIC_HARDENING_PLACEMENT_VERSION")
            old_tree = {item.node_code: item for item in semantic.hierarchy(system_code="commerce", effective_at=before_move, tenant_id=tenant_a, active_sources=(restaurant_source,))}
            new_tree = {item.node_code: item for item in semantic.hierarchy(system_code="commerce", effective_at=after_move, tenant_id=tenant_a, active_sources=(restaurant_source,))}
            if old_tree["wine"].path != ("Beverage", "Wine") or new_tree["wine"].path != ("Alcoholic Beverages", "Wine"):
                raise RuntimeError("SEMANTIC_HARDENING_HISTORICAL_PLACEMENT")

            views = semantic.classifications(tenant_id=tenant_a, target_type="atomic_unit", target_key=str(unit_a), effective_at=before_move, active_sources=(restaurant_source,))
            if len(views) != 1 or views[0].path != ("Beverage", "Bières") or views[0].source_key != restaurant_source:
                raise RuntimeError("SEMANTIC_HARDENING_OBJECT_VIEW")
            matrix = semantic.matrix(tenant_id=tenant_a, targets=(("atomic_unit", str(unit_a)),), system_codes=("commerce", "finance"), effective_at=before_move, active_sources=(restaurant_source,))
            if matrix[f"atomic_unit:{unit_a}"]["commerce"] != ("Beverage / Bières",) or matrix[f"atomic_unit:{unit_a}"]["finance"] != ():
                raise RuntimeError("SEMANTIC_HARDENING_MATRIX_VIEW")
            graph = semantic.graph(node_public_id=beer.public_id, effective_at=before_move, tenant_id=tenant_a, active_sources=(restaurant_source,))
            if str(pack_beer.public_id) not in graph["children"]:
                raise RuntimeError("SEMANTIC_HARDENING_GRAPH_VIEW")

            if any(issue.severity.value == "error" for issue in semantic.health(effective_at=before_move, tenant_id=tenant_a, active_sources=(restaurant_source,))):
                raise RuntimeError("SEMANTIC_HARDENING_HEALTH_FALSE_ERROR")
            orphan = session.execute(text("""INSERT INTO semantic_taxonomy_nodes(taxonomy_system_id,semantic_concept_id,tenant_id,node_code)
                SELECT s.id,c.id,NULL,'health_orphan' FROM taxonomy_systems s
                JOIN semantic_namespaces ns ON ns.namespace_code='sc41.kernel'
                JOIN semantic_concepts c ON c.namespace_id=ns.id AND c.code='beer'
                WHERE s.system_code='commerce' RETURNING id""")).scalar_one()
            health = semantic.health(effective_at=before_move, tenant_id=tenant_a, active_sources=(restaurant_source,))
            if not any(issue.code == "missing_effective_placement" for issue in health):
                raise RuntimeError("SEMANTIC_HARDENING_HEALTH_MISSED_ORPHAN")
            session.execute(text("DELETE FROM semantic_taxonomy_nodes WHERE id=:id"), {"id": orphan})

            try:
                semantic.assign(AssignSemanticClassification(
                    "unknown-target", tenant_a, "unknown_target", "x", "sc41.kernel:beer", start,
                    beer.public_id, AssignmentMode.EXPLICIT, SemanticSource.TENANT, f"tenant:{tenant_a}", {},
                ))
            except SemanticAuthorityError as exc:
                if exc.code != "unknown_classification_target_type":
                    raise
            else:
                raise RuntimeError("SEMANTIC_HARDENING_UNKNOWN_TARGET_ACCEPTED")

            # A global node cannot inherit from tenant-local structure.
            try:
                with session.begin_nested():
                    semantic.create_taxonomy_node(CreateTaxonomyNode(
                        "invalid-global-child", "commerce", "sc41.kernel:beer", "invalid_global_child", start,
                        parent_node_public_id=tenant_special.public_id, source_key="xbos.global",
                    ))
            except SemanticAuthorityError:
                pass
            else:
                raise RuntimeError("SEMANTIC_HARDENING_GLOBAL_TO_TENANT_PARENT_ACCEPTED")

        # Downgrade/re-upgrade proves the additive descendant is reversible without touching frozen tables.
        _run(command.downgrade, cfg, test_url, PREVIOUS)
        with test_engine.connect() as connection:
            if NEW_TABLES & _schema_tables(connection):
                raise RuntimeError("SEMANTIC_HARDENING_DOWNGRADE_LEFT_TABLES")
        _run(command.upgrade, cfg, test_url, HEAD)
        with test_engine.connect() as connection:
            _verify_schema(connection)

        # Controlled development adoption: exact predecessor may advance once; accepted head is read-only on repeat.
        dev_url = url.render_as_string(hide_password=False)
        with application_engine.connect() as connection:
            dev_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            action = _development_action(dev_head)
            before_tables = _schema_tables(connection)
            before_counts = _counts(connection, before_tables)
        if action == "UPGRADE":
            _run(command.upgrade, Config(str(ROOT / "alembic_neutral.ini")), dev_url, HEAD)
        with application_engine.connect() as connection:
            _verify_schema(connection)
            after_tables = _schema_tables(connection)
            after_counts = _counts(connection, before_tables)
            if before_counts != after_counts:
                raise RuntimeError("SEMANTIC_HARDENING_DEVELOPMENT_DATA_MUTATION")
            if action == "VERIFY_IN_PLACE" and before_tables != after_tables:
                raise RuntimeError("SEMANTIC_HARDENING_REPEAT_SCHEMA_MUTATION")

        return {
            "disposable_replay": "PASS",
            "global_taxonomy": "PASS",
            "pack_composition": "PASS",
            "tenant_overlay": "PASS",
            "root_parent_override": "PASS",
            "effective_cycle_guard": "PASS",
            "tenant_extension_isolation": "PASS",
            "tenant_qualified_idempotency": "PASS",
            "historical_placement": "PASS",
            "target_governance": "PASS",
            "hierarchy_object_matrix_graph_health": "PASS",
            "payments_only_neutrality": "PASS",
            "downgrade_reupgrade": "PASS",
            "development_head": HEAD,
            "development_action": action,
            "existing_data": "UNCHANGED",
        }
    finally:
        if test_engine is not None:
            test_engine.dispose()
        drop_test()
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
        print("SEMANTIC_HARDENING_VERIFY=FAIL\n" + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("SEMANTIC_HARDENING_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
