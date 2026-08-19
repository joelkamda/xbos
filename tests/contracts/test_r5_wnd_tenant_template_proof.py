from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from core.platform.operating_context import BusinessTimeResolver
from pack_platform.contracts import PackStatus, TenantPackState
from restaurant.r5 import (
    COUNTER_TEMPLATE_CODE,
    FULL_SERVICE_TEMPLATE_CODE,
    PACK_CODE,
    PACK_VERSION,
    WND_PROOF_TENANT_CODE,
    activate_restaurant_pack,
    apply_wnd_operating_context,
    build_composition_plan,
    build_provision_command,
    build_restaurant_templates,
    build_wnd_calendar,
    build_wnd_profile,
    configuration_keys,
    plan_and_apply_wnd_template,
    plan_fingerprint,
    register_templates,
)


ROOT = Path(__file__).resolve().parents[2]


def test_r5_registers_counter_and_full_service_templates_over_same_restaurant_pack():
    templates = build_restaurant_templates()
    assert templates.counter_service.template_code == COUNTER_TEMPLATE_CODE
    assert templates.full_service.template_code == FULL_SERVICE_TEMPLATE_CODE
    for template in (templates.counter_service, templates.full_service):
        assert template.version == "1.0.0"
        assert template.owner_code == "restaurant"
        assert len(template.requirements) == 1
        requirement = template.requirements[0]
        assert (requirement.pack_code, requirement.version, requirement.kind.value) == (
            PACK_CODE,
            PACK_VERSION,
            "required",
        )
        assert template.finance_kernel_required is True


def test_full_service_capability_is_not_reduced_to_wnd_profile():
    templates = build_restaurant_templates()
    counter = templates.counter_service.configuration_defaults["restaurant"]
    full = templates.full_service.configuration_defaults["restaurant"]
    assert counter["tables"]["enabled"] is False
    assert counter["reservations"]["enabled"] is False
    assert counter["fulfillment"]["course_firing"]["enabled"] is False
    assert full["tables"]["enabled"] is True
    assert full["reservations"]["enabled"] is True
    assert full["fulfillment"]["course_firing"]["enabled"] is True


def test_wnd_is_proof_tenant_pinned_to_explicit_template_not_production_identity():
    profile = build_wnd_profile()
    assert profile.profile_code == "wnd.logpom"
    assert profile.structure.tenant_code == WND_PROOF_TENANT_CODE
    assert profile.structure.location_code == "LOGPOM"
    assert profile.template_code == COUNTER_TEMPLATE_CODE
    assert profile.template_version == "1.0.0"
    assert profile.production_cutover_authorized is False


def test_wnd_template_overrides_do_not_mutate_template_defaults():
    templates = build_restaurant_templates()
    before = json.loads(json.dumps(templates.counter_service.configuration_defaults))
    profile = build_wnd_profile()
    assert profile.template_overrides["restaurant.commissions.enabled"] is True
    assert profile.template_overrides["restaurant.tips.enabled"] is False
    assert templates.counter_service.configuration_defaults == before
    assert templates.counter_service.configuration_defaults["restaurant"]["commissions"]["enabled"] is False


def test_wnd_pc4_calendar_proves_08_to_08_and_18_cutoff():
    calendar = build_wnd_calendar(501)
    cases = (
        ("2026-08-19T06:59:00+00:00", "night", "2026-08-18"),  # 07:59 Douala
        ("2026-08-19T07:00:00+00:00", "day", "2026-08-19"),    # 08:00 Douala
        ("2026-08-19T16:59:00+00:00", "day", "2026-08-19"),   # 17:59 Douala
        ("2026-08-19T17:00:00+00:00", "night", "2026-08-19"), # 18:00 Douala
    )
    for stamp, shift, business_date in cases:
        resolved = BusinessTimeResolver.resolve(calendar, datetime.fromisoformat(stamp))
        assert resolved.shift_code == shift
        assert resolved.business_date.isoformat() == business_date


def test_18_cutoff_changes_shift_not_commission_owner():
    profile = build_wnd_profile()
    assert profile.calendar.payment_shift_cutoff.isoformat() == "18:00:00"
    assert profile.calendar.commission_attribution_basis == "original_order_creator"


def test_payment_methods_are_tenant_configuration_not_restaurant_template_law():
    profile = build_wnd_profile()
    assert profile.payment_configuration["settlement_methods"] == ["cash", "mtn", "orange"]
    assert "split" in profile.payment_configuration["composition_options"]
    assert "unpaid_receivable" in profile.payment_configuration["composition_options"]
    templates = build_restaurant_templates()
    assert "payments" not in templates.counter_service.configuration_defaults["restaurant"]


def test_branding_and_terminology_are_tenant_localization_data():
    branding = build_wnd_profile().branding
    assert branding.business_display_name == "Wine & Dine"
    assert branding.terminology["cashier"] == "Cashier"
    assert not branding.branding_asset_reference.startswith(("data:", "file:"))


def test_provision_command_uses_pc1_canonical_logpom_structure():
    command = build_provision_command()
    assert command.tenant_code == WND_PROOF_TENANT_CODE
    assert command.primary_location_code == "LOGPOM"
    assert command.primary_location_name == "Logpom"
    assert command.timezone == "Africa/Douala"
    assert command.currency == "XAF"


class FakePackAuthority:
    def __init__(self):
        self.commands = []

    def stage(self, command):
        self.commands.append(command)
        return TenantPackState(UUID(int=1), command.tenant_id, command.pack_code, command.version, PackStatus.STAGED, 1, True)

    def install(self, command):
        self.commands.append(command)
        assert command.expected_row_version == 1
        return TenantPackState(UUID(int=1), command.tenant_id, command.pack_code, command.version, PackStatus.INSTALLED, 2, True)

    def activate(self, command):
        self.commands.append(command)
        assert command.expected_row_version == 2
        return TenantPackState(UUID(int=1), command.tenant_id, command.pack_code, command.version, PackStatus.ACTIVE, 3, True)


def test_pack_lifecycle_is_stage_install_activate_through_public_authority():
    authority = FakePackAuthority()
    result = activate_restaurant_pack(authority, 77)
    assert result.status is PackStatus.ACTIVE
    assert [type(x).__name__ for x in authority.commands] == ["StagePack", "InstallPack", "ActivatePack"]
    assert all(x.pack_code == PACK_CODE for x in authority.commands)


class FakeTemplateAuthority:
    def __init__(self):
        self.registered = []
        self.planned = None
        self.applied = None

    def register_template(self, command):
        self.registered.append(command)
        return SimpleNamespace(template_code=command.template.template_code, version=command.template.version)

    def plan_application(self, command):
        self.planned = command
        return SimpleNamespace(plan_sha256="a" * 64, conflicts=(), preserved_overrides=command.overrides)

    def apply_template(self, command):
        self.applied = command
        return SimpleNamespace(
            tenant_id=command.tenant_id,
            template_code=command.template_code,
            version=command.version,
            effective_configuration={},
        )


def test_template_registration_and_wnd_application_use_pk_public_commands():
    authority = FakeTemplateAuthority()
    records = register_templates(authority)
    assert [x.template_code for x in records] == [COUNTER_TEMPLATE_CODE, FULL_SERVICE_TEMPLATE_CODE]
    plan, state = plan_and_apply_wnd_template(authority, 88)
    assert authority.planned.template_code == COUNTER_TEMPLATE_CODE
    assert authority.applied.template_code == COUNTER_TEMPLATE_CODE
    assert authority.applied.plan_sha256 == plan.plan_sha256
    assert state.tenant_id == 88
    assert authority.planned.overrides == build_wnd_profile().template_overrides


class FakeOperatingAuthority:
    def __init__(self):
        self.definitions = []
        self.values = []
        self.calendars = []
        self.localizations = []

    def define(self, command):
        self.definitions.append(command)
        return command

    def set_value(self, command):
        self.values.append(command)
        return command

    def register_calendar(self, command):
        self.calendars.append(command)
        return 1

    def set_localization(self, command):
        self.localizations.append(command)
        return 1


def test_effective_template_configuration_is_materialized_via_pc4_public_authority():
    templates = build_restaurant_templates()
    effective = json.loads(json.dumps(templates.counter_service.configuration_defaults))
    effective["restaurant"]["service_modes"]["enabled"] = ["dine_in", "takeaway", "delivery"]
    effective["restaurant"]["tips"]["enabled"] = False
    effective["restaurant"]["commissions"]["enabled"] = True
    authority = FakeOperatingAuthority()
    calendar = apply_wnd_operating_context(authority, 99, effective)
    assert len(authority.definitions) == len(configuration_keys()) == 11
    assert len(authority.values) == 11
    assert len(authority.calendars) == 1
    assert len(authority.localizations) == 1
    assert calendar.business_day_boundary.isoformat() == "08:00:00"


def test_r5_mapping_contracts_defer_production_data_migration_to_r6():
    mapping = json.loads((ROOT / "contracts/restaurant/v1/r5_wnd_migration_mapping_plan.json").read_text())
    taxonomy = json.loads((ROOT / "contracts/restaurant/v1/r5_taxonomy_overlay_plan.json").read_text())
    assert mapping["execution"] == "R6_ONLY"
    assert mapping["production_data_moved_in_r5"] is False
    assert mapping["finance"]["r5_finance_writer"] is False
    assert mapping["inventory"]["r5_inventory_writer"] is False
    assert taxonomy["execution"]["r5"] == "PLAN_AND_PROOF_ONLY"
    assert taxonomy["execution"]["bulk_rewrite"] is False


def test_r5_source_has_no_direct_sql_or_private_repository_access():
    source = (ROOT / "restaurant/r5/service.py").read_text(encoding="utf-8").lower()
    for token in (
        "sql_repository",
        "from database import",
        "session.execute",
        "insert into",
        "update pk_",
        "delete from",
        "update financial_",
        "update inventory_",
    ):
        assert token not in source


def test_r5_has_no_schema_migration_or_r5_tables():
    assert not list((ROOT / "alembic_neutral/versions").glob("r5_*"))
    assert not list((ROOT / "alembic_neutral/sql").glob("r5_*"))


def test_r5_source_checkpoint_and_r6_readiness():
    authority = json.loads((ROOT / "contracts/restaurant/v1/r5_wnd_tenant_template_authority.json").read_text())
    ready = json.loads((ROOT / "contracts/restaurant/v1/r5_r6_readiness.json").read_text())
    assert authority["source_checkpoint"] == "7b52093f6fcbe264a56bb1cf673c937488125a3f"
    assert authority["accepted_head"] == "r2_restaurant_menu_fulfillment_043"
    assert authority["migration"] == "NONE"
    assert authority["production"]["changed"] is False
    assert ready["status"] == "READY_WHEN_R5_SINGLE_GATE_PASS"


def test_r5_composition_fingerprint_is_deterministic():
    first = plan_fingerprint()
    second = build_composition_plan().metadata["plan_fingerprint"]
    assert first == second and len(first) == 64
