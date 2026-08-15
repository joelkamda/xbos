"""PK4-PK6 conformance and deterministic template-composition authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .pk456_contracts import *

_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9.-]+)?$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PATH = re.compile(r"^[a-z][a-z0-9_.-]{1,159}$")
_SECRET_KEYS = {"password", "api_key", "access_token", "secret_value", "private_key", "client_secret", "credential"}
_REQUIRED_CERTIFICATION_CHECKS = {
    "architecture",
    "tenant_isolation",
    "migration_compatibility",
    "authorization",
    "semantics",
    "finance",
    "shared_operations",
    "xa",
    "manifest",
}


class PK456AuthorityError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: _primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_primitive(v) for v in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _fingerprint(kind: str, value: Any) -> str:
    return hashlib.sha256((kind + "\0" + _canonical(value)).encode("utf-8")).hexdigest()


def _token(value: str, field: str) -> str:
    value = str(value).strip().lower()
    if not _TOKEN.fullmatch(value):
        raise PK456AuthorityError("PK456_INVALID_TOKEN", field)
    return value


def _version(value: str) -> str:
    value = str(value).strip()
    if not _VERSION.fullmatch(value):
        raise PK456AuthorityError("PK456_INVALID_VERSION", value)
    return value


def _override_path(value: str) -> str:
    value = str(value).strip().lower()
    if not _PATH.fullmatch(value):
        raise PK456AuthorityError("PK456_INVALID_OVERRIDE_PATH", value)
    return value


def _scan_secret_material(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            low = str(key).lower()
            if low in _SECRET_KEYS or low.endswith("_password") or low.endswith("_secret"):
                raise PK456AuthorityError("PK456_SECRET_MATERIAL_FORBIDDEN", f"{path}.{key}")
            _scan_secret_material(item, f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _scan_secret_material(item, f"{path}[{index}]")


def _merge_configuration(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(defaults))
    for path, value in sorted(overrides.items()):
        cursor = result
        parts = path.split(".")
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value
    return result


class PK456Authority:
    """Conformance evidence and template composition without owning referenced truths."""

    def __init__(self, repository):
        self.repository = repository

    def certify(self, command: CertifyPackVersion) -> PackCertificationRecord:
        code = _token(command.pack_code, "pack_code")
        version = _version(command.version)
        certification_code = _token(command.certification_code, "certification_code")
        suite_version = _version(command.suite_version)
        checks = {str(k): ConformanceResult(v) for k, v in command.evidence.checks.items()}
        if set(checks) != _REQUIRED_CERTIFICATION_CHECKS:
            raise PK456AuthorityError("PK456_CONFORMANCE_CHECK_COVERAGE")
        if any(value is not ConformanceResult.PASS for value in checks.values()):
            raise PK456AuthorityError("PK456_CONFORMANCE_FAILED")
        evidence = tuple(sorted(set(command.evidence.evidence_sha256)))
        if not evidence or any(not _SHA.fullmatch(item) for item in evidence):
            raise PK456AuthorityError("PK456_EVIDENCE_HASH_INVALID")
        _scan_secret_material(command.evidence.notes, "certification.notes")
        pack = self.repository.pack_version(code, version)
        if pack is None:
            raise PK456AuthorityError("PK456_PACK_VERSION_NOT_FOUND")
        evidence_fingerprint = _sha({"checks": checks, "evidence": evidence, "notes": command.evidence.notes})
        fingerprint = _fingerprint("certify_pack", {"command": command, "evidence_fingerprint": evidence_fingerprint})
        return self.repository.certify(
            command.command_key,
            fingerprint,
            code,
            version,
            certification_code,
            suite_version,
            pack["manifest_sha256"],
            evidence_fingerprint,
            checks,
            command.evidence.notes,
        )

    def register_template(self, command: RegisterTemplateVersion) -> TemplateVersionRecord:
        template = self._validate_template(command.template)
        canonical = _canonical(template)
        fingerprint = _fingerprint("register_template", template)
        return self.repository.register_template(command.command_key, fingerprint, template, canonical, hashlib.sha256(canonical.encode()).hexdigest())

    def _validate_template(self, template: TemplateDefinition) -> TemplateDefinition:
        code = _token(template.template_code, "template_code")
        owner = _token(template.owner_code, "owner_code")
        version = _version(template.version)
        industry = str(template.industry_semantic_ref).strip()
        operating = str(template.operating_model_semantic_ref).strip()
        if ":" not in industry or ":" not in operating:
            raise PK456AuthorityError("PK456_SEMANTIC_REFERENCE_REQUIRED")
        requirements: list[TemplatePackRequirement] = []
        identities: set[tuple[str, TemplateRequirementKind]] = set()
        by_code: dict[str, set[TemplateRequirementKind]] = {}
        for row in template.requirements:
            pack_code = _token(row.pack_code, "requirement.pack_code")
            pack_version = _version(row.version)
            kind = TemplateRequirementKind(row.kind)
            identity = (pack_code, kind)
            if identity in identities:
                raise PK456AuthorityError("PK456_DUPLICATE_TEMPLATE_REQUIREMENT", pack_code)
            identities.add(identity)
            by_code.setdefault(pack_code, set()).add(kind)
            requirements.append(TemplatePackRequirement(pack_code, pack_version, kind))
        if any(len(kinds) > 1 for kinds in by_code.values()):
            raise PK456AuthorityError("PK456_CONFLICTING_TEMPLATE_REQUIREMENT")
        allowed = tuple(sorted({_override_path(path) for path in template.allowed_override_paths}))
        _scan_secret_material(template.configuration_defaults, "template.configuration_defaults")
        _scan_secret_material(template.xa, "template.xa")
        _scan_secret_material(template.terminology, "template.terminology")
        if not template.finance_kernel_required:
            raise PK456AuthorityError("PK456_FINANCE_KERNEL_CANNOT_BE_DISABLED")
        semantic_refs = tuple(sorted({str(value).strip() for value in template.semantic_references if str(value).strip()}))
        return TemplateDefinition(
            code,
            version,
            owner,
            industry,
            operating,
            tuple(sorted(requirements, key=lambda x: (x.pack_code, x.kind.value, x.version))),
            allowed,
            _primitive(template.configuration_defaults),
            {str(k): str(v) for k, v in sorted(template.terminology.items())},
            _primitive(template.xa),
            semantic_refs,
            bool(template.finance_workspace_exposed),
            True,
        )

    def plan_application(self, command: PlanTemplateApplication) -> TemplatePlan:
        template = self.repository.template_version(_token(command.template_code, "template_code"), _version(command.version))
        if template is None:
            raise PK456AuthorityError("PK456_TEMPLATE_VERSION_NOT_FOUND")
        selected = tuple(sorted({_token(value, "selected_optional_pack") for value in command.selected_optional_packs}))
        overrides = {_override_path(path): value for path, value in command.overrides.items()}
        _scan_secret_material(overrides, "template.overrides")
        return self._plan(command.tenant_id, template, selected, overrides, from_version=None)

    def apply_template(self, command: ApplyTemplate) -> TenantTemplateState:
        fingerprint = _fingerprint("apply_template", command)
        replay = self.repository.template_command_replay(command.tenant_id, command.command_key, fingerprint, "apply_template")
        if replay is not None:
            return replay
        plan = self.plan_application(PlanTemplateApplication(command.tenant_id, command.template_code, command.version, command.selected_optional_packs, command.overrides))
        if plan.plan_sha256 != command.plan_sha256:
            raise PK456AuthorityError("PK456_PLAN_FINGERPRINT_MISMATCH")
        if plan.conflicts:
            raise PK456AuthorityError("PK456_TEMPLATE_PLAN_CONFLICT", ",".join(plan.conflicts))
        self._require_active_pack_preconditions(command.tenant_id, plan.required_packs, plan.optional_packs)
        return self.repository.apply_template(command, fingerprint, plan)

    def plan_upgrade(self, command: PlanTemplateUpgrade) -> TemplatePlan:
        state = self.repository.tenant_template(command.tenant_id, _token(command.template_code, "template_code"))
        if state is None:
            raise PK456AuthorityError("PK456_TEMPLATE_NOT_APPLIED")
        target = self.repository.template_version(state.template_code, _version(command.target_version))
        if target is None:
            raise PK456AuthorityError("PK456_TEMPLATE_VERSION_NOT_FOUND")
        selected = tuple(sorted(self.repository.selected_optional_packs(command.tenant_id, state.template_code)))
        return self._plan(command.tenant_id, target, selected, dict(state.overrides), from_version=state.version)

    def upgrade_template(self, command: UpgradeTemplate) -> TenantTemplateState:
        fingerprint = _fingerprint("upgrade_template", command)
        replay = self.repository.template_command_replay(command.tenant_id, command.command_key, fingerprint, "upgrade_template")
        if replay is not None:
            return replay
        plan = self.plan_upgrade(PlanTemplateUpgrade(command.tenant_id, command.template_code, command.target_version))
        if plan.plan_sha256 != command.plan_sha256:
            raise PK456AuthorityError("PK456_PLAN_FINGERPRINT_MISMATCH")
        if plan.conflicts:
            raise PK456AuthorityError("PK456_TEMPLATE_PLAN_CONFLICT", ",".join(plan.conflicts))
        self._require_active_pack_preconditions(command.tenant_id, plan.required_packs, plan.optional_packs)
        return self.repository.upgrade_template(command, fingerprint, plan)

    def _plan(self, tenant_id: int, template, selected: tuple[str, ...], overrides: dict[str, Any], from_version: str | None) -> TemplatePlan:
        allowed = set(template["allowed_override_paths"])
        invalid = sorted(set(overrides) - allowed)
        conflicts = [f"override_not_allowed:{path}" for path in invalid]
        requirements = template["requirements"]
        required_rows = [r for r in requirements if r["kind"] == TemplateRequirementKind.REQUIRED.value]
        optional_rows = [r for r in requirements if r["kind"] == TemplateRequirementKind.OPTIONAL.value]
        incompatible_rows = [r for r in requirements if r["kind"] == TemplateRequirementKind.INCOMPATIBLE.value]
        optional_codes = {r["pack_code"] for r in optional_rows}
        unknown_selected = sorted(set(selected) - optional_codes)
        conflicts.extend(f"optional_not_declared:{code}" for code in unknown_selected)
        required_packs = tuple(f"{r['pack_code']}@{r['version']}" for r in sorted(required_rows, key=lambda x: x["pack_code"]))
        selected_optional = tuple(f"{r['pack_code']}@{r['version']}" for r in sorted(optional_rows, key=lambda x: x["pack_code"]) if r["pack_code"] in selected)
        actions: list[str] = []
        for identity in (*required_packs, *selected_optional):
            code, version = identity.rsplit("@", 1)
            pack = self.repository.pack_version(code, version)
            if pack is None:
                conflicts.append(f"pack_version_missing:{identity}")
                continue
            if not self.repository.is_certified(code, version):
                conflicts.append(f"pack_not_certified:{identity}")
            installation = self.repository.pack_installation(tenant_id, code)
            if installation is None or installation["version"] != version or installation["status"] != "active":
                actions.append(f"ensure_pack_active:{identity}")
        for row in incompatible_rows:
            installation = self.repository.pack_installation(tenant_id, row["pack_code"])
            if installation is not None and installation["status"] in {"staged", "installed", "active", "disabled"}:
                conflicts.append(f"incompatible_pack_present:{row['pack_code']}")
        if template["configuration_defaults"]:
            actions.append("resolve_pc4_configuration_defaults_via_public_contract")
        if template["xa"]:
            actions.append("expose_xa_composition_metadata")
        preserved = {path: value for path, value in sorted(overrides.items()) if path in allowed}
        body = {
            "tenant_id": tenant_id,
            "template_code": template["template_code"],
            "from_version": from_version,
            "to_version": template["version"],
            "required_packs": required_packs,
            "optional_packs": selected_optional,
            "actions": sorted(set(actions)),
            "conflicts": sorted(set(conflicts)),
            "preserved_overrides": preserved,
            "template_sha256": template["template_sha256"],
        }
        return TemplatePlan(
            tenant_id,
            template["template_code"],
            from_version,
            template["version"],
            required_packs,
            selected_optional,
            tuple(body["actions"]),
            tuple(body["conflicts"]),
            preserved,
            _sha(body),
        )

    def _require_active_pack_preconditions(self, tenant_id: int, required: tuple[str, ...], optional: tuple[str, ...]) -> None:
        for identity in (*required, *optional):
            code, version = identity.rsplit("@", 1)
            installation = self.repository.pack_installation(tenant_id, code)
            if installation is None or installation["status"] != "active" or installation["version"] != version:
                raise PK456AuthorityError("PK456_PACK_PRECONDITION_NOT_ACTIVE", identity)
