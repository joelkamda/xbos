from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from pack_platform.pk456_contracts import *
from pack_platform.pk456_service import PK456Authority, PK456AuthorityError


PASS_CHECKS = {name: ConformanceResult.PASS for name in (
    "architecture", "tenant_isolation", "migration_compatibility", "authorization",
    "semantics", "finance", "shared_operations", "xa", "manifest",
)}


class FakeRepo:
    def __init__(self):
        self.packs = {
            ("neutral.foundation", "1.0.0"): {"manifest_sha256": "1" * 64},
            ("neutral.payments", "1.0.0"): {"manifest_sha256": "2" * 64},
        }
        self.certified = set()
        self.templates = {}
        self.installations = {}
        self.states = {}
        self.template_commands = {}

    def pack_version(self, code, version):
        return self.packs.get((code, version))

    def certify(self, key, fingerprint, code, version, certification_code, suite_version, manifest_sha256, evidence_sha256, checks, notes):
        self.certified.add((code, version))
        return PackCertificationRecord(uuid4(), code, version, certification_code, suite_version, manifest_sha256, evidence_sha256, ConformanceResult.PASS)

    def is_certified(self, code, version):
        return (code, version) in self.certified

    def register_template(self, key, fingerprint, template, canonical, sha):
        record = TemplateVersionRecord(uuid4(), template.template_code, template.version, template.owner_code, sha, template.industry_semantic_ref, template.operating_model_semantic_ref)
        self.templates[(template.template_code, template.version)] = {
            "template_id": 1,
            "id": len(self.templates) + 1,
            "template_code": template.template_code,
            "version": template.version,
            "owner_code": template.owner_code,
            "template_sha256": sha,
            "industry_semantic_ref": template.industry_semantic_ref,
            "operating_model_semantic_ref": template.operating_model_semantic_ref,
            "requirements": [{"pack_code": r.pack_code, "version": r.version, "kind": r.kind.value} for r in template.requirements],
            "allowed_override_paths": list(template.allowed_override_paths),
            "configuration_defaults": template.configuration_defaults,
            "xa": template.xa,
        }
        return record

    def template_version(self, code, version):
        return self.templates.get((code, version))

    def pack_installation(self, tenant_id, code):
        return self.installations.get((tenant_id, code))

    def template_command_replay(self, tenant_id, command_key, fingerprint, command_type):
        identity = (tenant_id, command_key)
        row = self.template_commands.get(identity)
        if row is None:
            return None
        if row["fingerprint"] != fingerprint or row["command_type"] != command_type:
            raise PK456AuthorityError("PK456_COMMAND_CONFLICT")
        return row.get("result")

    def apply_template(self, command, fingerprint, plan):
        template = self.template_version(command.template_code, command.version)
        effective = dict(template["configuration_defaults"])
        state = TenantTemplateState(uuid4(), command.tenant_id, command.template_code, command.version, 1, template["template_sha256"], dict(plan.preserved_overrides), effective)
        self.states[(command.tenant_id, command.template_code)] = state
        self.template_commands[(command.tenant_id, command.command_key)] = {"fingerprint": fingerprint, "command_type": "apply_template", "result": state}
        return state

    def tenant_template(self, tenant_id, template_code):
        return self.states.get((tenant_id, template_code))

    def selected_optional_packs(self, tenant_id, template_code):
        return ()

    def upgrade_template(self, command, fingerprint, plan):
        old = self.states[(command.tenant_id, command.template_code)]
        target = self.template_version(command.template_code, command.target_version)
        state = replace(old, version=command.target_version, row_version=old.row_version + 1, template_sha256=target["template_sha256"], overrides=dict(plan.preserved_overrides))
        self.states[(command.tenant_id, command.template_code)] = state
        self.template_commands[(command.tenant_id, command.command_key)] = {"fingerprint": fingerprint, "command_type": "upgrade_template", "result": state}
        return state


def payments_template(version="1.0.0", allowed=("branding.display_name", "payments.default_channel")):
    return TemplateDefinition(
        "neutral.payments_only", version, "pk", "industry:financial_operations", "operating_model:payments_only",
        (
            TemplatePackRequirement("neutral.foundation", "1.0.0", TemplateRequirementKind.REQUIRED),
            TemplatePackRequirement("neutral.payments", "1.0.0", TemplateRequirementKind.REQUIRED),
        ),
        allowed,
        {"payments": {"default_channel": "cash"}},
        {},
        {"accounting_workspace_exposed": False},
        (),
        False,
        True,
    )


def certify_all(authority):
    for code, sha in (("neutral.foundation", "a" * 64), ("neutral.payments", "b" * 64)):
        authority.certify(CertifyPackVersion(f"cert-{code}", code, "1.0.0", "pk-conformance", "1.0.0", PackCertificationEvidence(PASS_CHECKS, (sha,))))


def test_certification_requires_complete_passing_evidence():
    repo = FakeRepo(); authority = PK456Authority(repo)
    bad = dict(PASS_CHECKS); bad.pop("finance")
    try:
        authority.certify(CertifyPackVersion("c1", "neutral.payments", "1.0.0", "pk", "1.0.0", PackCertificationEvidence(bad, ("a" * 64,))))
        assert False
    except PK456AuthorityError as exc:
        assert exc.code == "PK456_CONFORMANCE_CHECK_COVERAGE"
    failed = dict(PASS_CHECKS); failed["finance"] = ConformanceResult.FAIL
    try:
        authority.certify(CertifyPackVersion("c2", "neutral.payments", "1.0.0", "pk", "1.0.0", PackCertificationEvidence(failed, ("a" * 64,))))
        assert False
    except PK456AuthorityError as exc:
        assert exc.code == "PK456_CONFORMANCE_FAILED"


def test_template_cannot_disable_finance_kernel_or_smuggle_secrets():
    authority = PK456Authority(FakeRepo())
    try:
        authority.register_template(RegisterTemplateVersion("r1", replace(payments_template(), finance_kernel_required=False)))
        assert False
    except PK456AuthorityError as exc:
        assert exc.code == "PK456_FINANCE_KERNEL_CANNOT_BE_DISABLED"
    try:
        authority.register_template(RegisterTemplateVersion("r2", replace(payments_template(), configuration_defaults={"api_key": "secret"})))
        assert False
    except PK456AuthorityError as exc:
        assert exc.code == "PK456_SECRET_MATERIAL_FORBIDDEN"


def test_application_plan_is_deterministic_and_requires_certified_active_packs():
    repo = FakeRepo(); authority = PK456Authority(repo)
    authority.register_template(RegisterTemplateVersion("r", payments_template()))
    plan = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    assert any(item.startswith("pack_not_certified:") for item in plan.conflicts)
    certify_all(authority)
    repo.installations[(1, "neutral.foundation")] = {"version": "1.0.0", "status": "active"}
    repo.installations[(1, "neutral.payments")] = {"version": "1.0.0", "status": "active"}
    first = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    second = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    assert first.plan_sha256 == second.plan_sha256 and first.conflicts == ()


def test_two_merchants_can_diverge_without_mutating_template():
    repo = FakeRepo(); authority = PK456Authority(repo)
    authority.register_template(RegisterTemplateVersion("r", payments_template()))
    certify_all(authority)
    for tenant in (1, 2):
        repo.installations[(tenant, "neutral.foundation")] = {"version": "1.0.0", "status": "active"}
        repo.installations[(tenant, "neutral.payments")] = {"version": "1.0.0", "status": "active"}
    p1 = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    p2 = authority.plan_application(PlanTemplateApplication(2, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "orange"}))
    s1 = authority.apply_template(ApplyTemplate("same-key", 1, "neutral.payments_only", "1.0.0", p1.plan_sha256, (), {"payments.default_channel": "mtn"}))
    s2 = authority.apply_template(ApplyTemplate("same-key", 2, "neutral.payments_only", "1.0.0", p2.plan_sha256, (), {"payments.default_channel": "orange"}))
    assert s1.template_sha256 == s2.template_sha256 and s1.overrides != s2.overrides


def test_upgrade_fails_when_existing_override_is_no_longer_allowed():
    repo = FakeRepo(); authority = PK456Authority(repo)
    authority.register_template(RegisterTemplateVersion("r1", payments_template("1.0.0")))
    authority.register_template(RegisterTemplateVersion("r2", payments_template("2.0.0", allowed=("branding.display_name",))))
    certify_all(authority)
    repo.installations[(1, "neutral.foundation")] = {"version": "1.0.0", "status": "active"}
    repo.installations[(1, "neutral.payments")] = {"version": "1.0.0", "status": "active"}
    plan = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    authority.apply_template(ApplyTemplate("apply", 1, "neutral.payments_only", "1.0.0", plan.plan_sha256, (), {"payments.default_channel": "mtn"}))
    upgrade = authority.plan_upgrade(PlanTemplateUpgrade(1, "neutral.payments_only", "2.0.0"))
    assert "override_not_allowed:payments.default_channel" in upgrade.conflicts


def test_sql_repository_template_projection_matches_public_contract():
    from pack_platform.pk456_sql_repository import SQLPK456Repository

    persisted = {
        "id": 7,
        "template_id": 3,
        "template_code": "neutral.payments_only",
        "template_version": "1.0.0",
        "template_sha256": "a" * 64,
        "allowed_override_paths": ["payments.default_channel"],
        "configuration_defaults": {"payments": {"default_channel": "cash"}},
        "terminology_json": {"payment": "payment"},
        "xa_json": {"primary_actions": ["receive", "pay", "transfer"]},
    }
    projected = SQLPK456Repository._template_projection(persisted)
    assert projected["version"] == "1.0.0"
    assert projected["xa"] == persisted["xa_json"]
    assert projected["terminology"] == persisted["terminology_json"]



def test_changed_apply_replay_reports_command_conflict_before_plan_mismatch():
    repo = FakeRepo(); authority = PK456Authority(repo)
    authority.register_template(RegisterTemplateVersion("r", payments_template()))
    certify_all(authority)
    repo.installations[(1, "neutral.foundation")] = {"version": "1.0.0", "status": "active"}
    repo.installations[(1, "neutral.payments")] = {"version": "1.0.0", "status": "active"}
    plan = authority.plan_application(PlanTemplateApplication(1, "neutral.payments_only", "1.0.0", (), {"payments.default_channel": "mtn"}))
    original = ApplyTemplate("same-key", 1, "neutral.payments_only", "1.0.0", plan.plan_sha256, (), {"payments.default_channel": "mtn"})
    state = authority.apply_template(original)
    assert authority.apply_template(original) == state
    changed = ApplyTemplate("same-key", 1, "neutral.payments_only", "1.0.0", plan.plan_sha256, (), {"payments.default_channel": "cash"})
    try:
        authority.apply_template(changed)
        assert False
    except PK456AuthorityError as exc:
        assert exc.code == "PK456_COMMAND_CONFLICT"
