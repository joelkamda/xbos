from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.platform.semantics.classification_hardening import (
    AssignmentMode,
    ClassificationTargetRegistry,
    CreateTaxonomyNode,
    CreateTaxonomySystem,
    SemanticClassificationAuthority,
    SemanticSource,
    SetTenantTaxonomyOverlay,
    TargetScope,
    TargetTypeDefinition,
)
from core.platform.semantics.classification_hardening.contracts import EffectiveTaxonomyNode, HealthIssue
from core.platform.semantics import SemanticAuthorityError
from scripts.verify_semantic_classification_hardening import HEAD, PREVIOUS, static_verify

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform/v1"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


class FakeRepository:
    def create_system(self, command, fingerprint):
        from core.platform.semantics.classification_hardening.contracts import TaxonomySystemDefinition
        return TaxonomySystemDefinition(1, UUID(int=1), command.system_code.lower(), command.owner_code, command.tenant_id, command.namespace_code.lower(), "active")

    def hierarchy_rows(self, system_code, effective_at, tenant_id, active_sources):
        return [
            {
                "node_public_id": UUID(int=10),
                "system_code": system_code,
                "node_code": "beverage",
                "concept_qualified_code": "kernel:beverage",
                "label": "Beverage",
                "tenant_id": None,
                "parent_public_id": None,
                "sort_order": 0,
                "source_type": SemanticSource.KERNEL,
                "source_key": "xbos.global",
                "inherited": True,
            },
            {
                "node_public_id": UUID(int=11),
                "system_code": system_code,
                "node_code": "beer",
                "concept_qualified_code": "kernel:beer",
                "label": "Beer",
                "tenant_id": None,
                "parent_public_id": UUID(int=10),
                "sort_order": 1,
                "source_type": SemanticSource.KERNEL,
                "source_key": "xbos.global",
                "inherited": True,
            },
        ]

    def classification_rows(self, tenant_id, target_type, target_key, effective_at, active_sources):
        return [
            {
                "tenant_id": tenant_id,
                "target_type": target_type,
                "target_key": target_key,
                "system_code": "commerce",
                "node_public_id": UUID(int=11),
                "node_code": "beer",
                "concept_qualified_code": "kernel:beer",
                "concept_version": 1,
                "label": "Beer",
                "assignment_mode": AssignmentMode.EXPLICIT,
                "source_type": SemanticSource.KERNEL,
                "source_key": "xbos.global",
                "effective_from": effective_at,
                "effective_to": None,
                "provenance": {},
            }
        ]

    def graph_rows(self, node_public_id, effective_at, tenant_id, active_sources):
        if node_public_id.int == 0:
            return {"systems": ("commerce",)}
        return {"node": str(node_public_id), "system_code": "commerce", "parent": str(UUID(int=10)), "children": (), "mappings": ()}

    def health_rows(self, effective_at, tenant_id, active_sources):
        return []


def authority() -> SemanticClassificationAuthority:
    targets = ClassificationTargetRegistry()
    targets.register(TargetTypeDefinition("atomic_unit", "SO1", TargetScope.TENANT, "uuid"), lambda tenant, key: tenant == 1 and key == "unit-1")
    return SemanticClassificationAuthority(FakeRepository(), targets)


def test_static_hardening_contract_and_lineage_are_complete():
    result = static_verify()
    assert result["status"] == "PASS"
    assert (result["previous_head"], result["accepted_head"]) == (PREVIOUS, HEAD)
    assert result["taxonomy_systems"] == 40


def test_global_registry_has_exactly_40_unique_logical_taxonomy_systems_with_domains():
    registry = load("sc41_global_taxonomy_registry.json")
    systems = registry["systems"]
    assert registry["taxonomy_system_count"] == len(systems) == 40
    assert len({row["system_code"] for row in systems}) == 40
    assert all(row["depth_1_domains"] for row in systems)
    assert registry["universal_tree"] is False
    assert "unbounded" in registry["depth_model"]


def test_depth_vocabulary_is_presentation_not_fixed_schema():
    registry = load("sc41_global_taxonomy_registry.json")
    assert "domain/category/subcategory" in registry["depth_model"]
    up = (ROOT / "alembic_neutral/sql/semantic_classification_hardening_up.sql").read_text(encoding="utf-8")
    assert "semantic_level" not in up
    assert "category" not in up.lower()
    assert "subcategory" not in up.lower()


def test_hardening_is_additive_and_does_not_rewrite_frozen_pc3_so1_or_legacy_taxonomy():
    authority_contract = load("sc41_semantic_classification_hardening.json")
    assert all(value is False for value in authority_contract["frozen_compatibility"].values())
    up = (ROOT / "alembic_neutral/sql/semantic_classification_hardening_up.sql").read_text(encoding="utf-8")
    for forbidden in (
        "ALTER TABLE public.taxonomy_nodes",
        "ALTER TABLE public.atomic_units",
        "ALTER TABLE public.atomic_unit_taxonomy",
        "ALTER TABLE public.semantic_commands",
    ):
        assert forbidden not in up


def test_global_nodes_history_tenant_overlay_and_governance_have_distinct_physical_roles():
    up = (ROOT / "alembic_neutral/sql/semantic_classification_hardening_up.sql").read_text(encoding="utf-8")
    for table in (
        "semantic_taxonomy_nodes",
        "semantic_taxonomy_placements",
        "tenant_taxonomy_overlays",
        "semantic_classification_governance",
        "semantic_classification_commands",
    ):
        assert f"CREATE TABLE public.{table}" in up
    assert "NULLS NOT DISTINCT" in up
    assert "overlapping_taxonomy_placement" in up
    assert "effective_taxonomy_cycle" in up
    assert "trg_sc41_tenant_taxonomy_overlay_effective_cycle" in up
    assert "trg_sc41_semantic_taxonomy_placement_effective_cycle" in up
    assert "semantic_taxonomy_placement_is_historical" in up
    assert "cross_tenant_taxonomy_overlay_forbidden" in up


def test_target_registry_is_explicit_owner_validated_and_fail_closed():
    service = authority()
    definition = service.targets.validate(1, "atomic_unit", "unit-1")
    assert definition.owner_code == "SO1"
    with pytest.raises(SemanticAuthorityError, match="classification_target_not_found_or_cross_tenant"):
        service.targets.validate(2, "atomic_unit", "unit-1")
    with pytest.raises(SemanticAuthorityError, match="unknown_classification_target_type"):
        service.targets.validate(1, "mystery", "x")


def test_hierarchy_and_object_views_join_semantics_without_owning_target():
    service = authority()
    at = datetime(2026, 8, 17, tzinfo=timezone.utc)
    hierarchy = service.hierarchy(system_code="commerce", effective_at=at, tenant_id=1)
    assert [item.path for item in hierarchy] == [("Beverage",), ("Beverage", "Beer")]
    views = service.classifications(tenant_id=1, target_type="atomic_unit", target_key="unit-1", effective_at=at)
    assert len(views) == 1 and views[0].path == ("Beverage", "Beer")
    matrix = service.matrix(tenant_id=1, targets=(("atomic_unit", "unit-1"),), system_codes=("commerce",), effective_at=at)
    assert matrix["atomic_unit:unit-1"]["commerce"] == ("Beverage / Beer",)


def test_public_contract_has_all_five_read_lenses_and_no_template_authority_duplication():
    interface = load("sc41_public_interfaces.json")
    assert set(interface["read_models"]) == {"hierarchy", "object_classifications", "matrix", "graph", "health"}
    authority_contract = load("sc41_semantic_classification_hardening.json")
    assert "taxonomy_systems" in authority_contract["existing_tables_reused"]
    assert not any(table.startswith("template_") for table in authority_contract["new_tables"])


def test_family_offer_recipe_inventory_and_finance_are_explicitly_outside_classification_scope():
    doc = (ROOT / "docs/platform_core/SEMANTIC_CLASSIFICATION_HARDENING_041.md").read_text(encoding="utf-8")
    for phrase in (
        "family / variant",
        "commercial composition",
        "operational composition",
        "inventory",
        "Finance",
    ):
        assert phrase in doc


def test_no_restaurant_or_wnd_semantics_are_hardcoded_in_active_implementation():
    forbidden = (b"wine & dine", b"logpom", b"wnd", b"main dish", b"restaurant core")
    for path in (ROOT / "core/platform/semantics/classification_hardening").rglob("*.py"):
        data = path.read_bytes().lower()
        assert not any(token in data for token in forbidden)



def test_tenant_parent_override_requires_explicit_flag_and_can_represent_root():
    service = authority()
    at = datetime(2026, 8, 17, tzinfo=timezone.utc)
    with pytest.raises(SemanticAuthorityError, match="taxonomy_parent_override_requires_explicit_flag"):
        service.set_tenant_overlay(SetTenantTaxonomyOverlay(
            "bad-parent-flag", 1, UUID(int=11), None, at,
            parent_override_public_id=UUID(int=10),
        ))
    # Root is represented unambiguously as has_parent_override=True + NULL parent.
    command = SetTenantTaxonomyOverlay(
        "root-parent", 1, UUID(int=11), None, at,
        parent_override_public_id=None, has_parent_override=True,
    )
    assert command.has_parent_override is True and command.parent_override_public_id is None

def test_release_metadata_records_no_direct_business_or_finance_change():
    contract = load("sc41_semantic_classification_hardening.json")
    assert contract["restaurant_pack_change"] == "NONE"
    assert contract["wnd_production_change"] == "NONE"
    assert contract["dependencies"] == "UNCHANGED"
    assert contract["frozen_compatibility"]["finance_authority_implementation_modified"] is False
    assert contract["release_integrity"]["cumulative_release_metadata_refreshed"] is True
    assert contract["release_integrity"]["authority_or_business_implementation_change_from_refresh"] == "NONE"


def test_template_may_select_semantics_but_cannot_author_taxonomy_placement():
    service = authority()
    with pytest.raises(SemanticAuthorityError, match="template_cannot_author_taxonomy_placement"):
        service.create_taxonomy_node(CreateTaxonomyNode(
            "template-placement", "commerce", "kernel:beer", "beer",
            datetime(2026, 8, 17, tzinfo=timezone.utc),
            source_type=SemanticSource.TEMPLATE,
            source_key="restaurant.core@1.0.0",
        ))


def test_pc3_date_effective_semantics_are_timezone_independent():
    repository = (ROOT / "core/platform/semantics/classification_hardening/sql_repository.py").read_text(encoding="utf-8")
    assert "def _semantic_date" in repository
    assert "astimezone(timezone.utc).date()" in repository
    assert "CAST(:on AS date)" not in repository
    assert "v.effective_from<=:semantic_date" in repository



def test_classification_read_model_interpolates_visible_source_predicate_before_sql_execution():
    repository = (ROOT / "core/platform/semantics/classification_hardening/sql_repository.py").read_text(encoding="utf-8")
    assert 'text(f"""SELECT a.tenant_id,a.subject_type AS target_type' in repository
    assert 'text("""SELECT a.tenant_id,a.subject_type AS target_type' not in repository
