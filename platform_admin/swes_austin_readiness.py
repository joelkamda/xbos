"""Source-backed fail-closed PA readiness for exactly SWES Austin TEST tenant 910001.

This module only issues SELECTs and invokes read-only PK456/PC4/PC5 public
authority methods. It never writes onboarding state or grants permissions.
Evidence references are local integrity digests, NOT independent signatures.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID

from sqlalchemy import text

from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
from core.platform.operating_context.service import OperatingContextAuthority
from core.platform.operating_context.contracts import ConfigScope
from core.platform.structure.contracts import TenantLifecycle
from core.platform.structure.service import StructuralAuthority
from core.platform.structure.sql_repository import SQLStructuralRepository
from core.platform.security_authority.contracts import (
    ActorType,
    AuthorizationRequest,
    Decision,
    ScopeType,
    StructuralScope,
)
from core.platform.security_authority.service import SecurityAuthority
from core.platform.security_authority.sql_repository import SQLSecurityRepository
from pack_platform.pk456_contracts import PlanTemplateApplication
from pack_platform.pk456_service import PK456Authority
from pack_platform.pk456_sql_repository import SQLPK456Repository


CHECKS = (
    "pc1_tenant_available",
    "pk_template_pinned",
    "pc4_entitlements_effective",
    "pc5_tenant_admin_ready",
)
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")


class SWESAustinReadinessHold(RuntimeError):
    """Fail-closed diagnostic without copying underlying protected rows."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SWESAustinReadinessScope:
    tenant_id: int
    tenant_code: str
    currency: str
    location_id: int
    template_code: str
    template_version: str
    entitlement_modules: Mapping[str, str]
    pc5_session_public_id: UUID | None
    pc5_permission_code: str
    pc5_capability_code: str
    pc5_admin_role_code: str = ""

    def __post_init__(self):
        if (self.tenant_id, self.tenant_code, self.currency, self.location_id) != (
            910001, "SWES_WND_AUSTIN_TEST", "XAF", 5
        ):
            raise SWESAustinReadinessHold("HOLD_TARGET_NOT_SWES_AUSTIN_TEST")
        if not self.template_code or not self.template_version:
            raise SWESAustinReadinessHold("HOLD_TEMPLATE_UNSPECIFIED")
        if any(
            not _CODE.fullmatch(k) or not _CODE.fullmatch(v)
            for k, v in self.entitlement_modules.items()
        ):
            raise SWESAustinReadinessHold("HOLD_PC4_MODULE_MAPPING_INVALID")
        if self.pc5_session_public_id is not None and not isinstance(
            self.pc5_session_public_id, UUID
        ):
            raise SWESAustinReadinessHold("HOLD_PC5_SESSION_ID_INVALID")


def _reference(prefix: str, attributes: Mapping) -> str:
    """Stable nonsecret digest of source-verified claim, not an attestation."""
    payload = json.dumps(
        attributes, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return f"{prefix}:sha256:{hashlib.sha256(payload).hexdigest()}"


def _one_or_none(session, statement: str, parameters: dict):
    rows = session.execute(text(statement), parameters).mappings().all()
    if len(rows) > 1:
        raise SWESAustinReadinessHold("HOLD_AMBIGUOUS_AUTHORITY_ROWS")
    return dict(rows[0]) if rows else None


class SWESAustinReadinessGateway:
    """A real PA ReadinessGateway based on canonical source-owned records.

    No synthetic PASS is possible: each PASS requires an exact source-owned
    row or an ALLOW from the existing PC5 authorization service.
    """

    def __init__(self, session, scope: SWESAustinReadinessScope, *, at: datetime | None = None):
        self.session = session
        self.scope = scope
        self.at = at or datetime.now(timezone.utc)
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise SWESAustinReadinessHold("HOLD_TIMEZONE_REQUIRED")
        self.details: dict[str, str] = {}

    def assess(
        self,
        *,
        tenant_id: int,
        template_code: str,
        template_version: str,
        entitlement_codes: tuple[str, ...],
    ) -> dict[str, tuple[str, str]]:
        if (
            tenant_id != self.scope.tenant_id
            or template_code != self.scope.template_code
            or template_version != self.scope.template_version
        ):
            raise SWESAustinReadinessHold("HOLD_READINESS_SCOPE_MISMATCH")
        result: dict[str, tuple[str, str]] = {}
        checks = (
            ("pc1_tenant_available", self._pc1),
            ("pk_template_pinned", self._pk),
            ("pc4_entitlements_effective", lambda: self._pc4(entitlement_codes)),
            ("pc5_tenant_admin_ready", self._pc5),
        )
        for code, inspect in checks:
            try:
                reference = inspect()
                if not reference:
                    raise SWESAustinReadinessHold("HOLD_EMPTY_EVIDENCE")
                result[code] = ("pass", reference)
                self.details[code] = "PASS"
            except Exception as exc:
                # A DB error, missing table, inconsistent record, or denied
                # authorization always becomes FAIL. Never convert it to PASS.
                hold = exc.code if isinstance(exc, SWESAustinReadinessHold) else (
                    "HOLD_SOURCE_UNAVAILABLE"
                )
                self.details[code] = hold
                result[code] = ("fail", _reference(
                    code, {"result": "FAIL", "hold": hold, "at": self.at.isoformat()}
                ))
        return result

    def _pc1(self) -> str:
        """Resolve the existing SWES Austin TEST tenant and virtual location via PC1."""
        pc1 = StructuralAuthority(SQLStructuralRepository(self.session))
        context = pc1.resolve(tenant_id=self.scope.tenant_id,
                              location_id=self.scope.location_id)
        tenant, location = context.tenant, context.location
        if (tenant.code != self.scope.tenant_code
                or tenant.currency != self.scope.currency
                or tenant.lifecycle is not TenantLifecycle.ACTIVE
                or tenant.row_version < 1
                or location is None or location.code != "swes-wnd-austin-virtual"
                or not location.active or location.row_version < 1):
            raise SWESAustinReadinessHold("HOLD_PC1_TENANT_LOCATION_UNAVAILABLE")
        return _reference("pc1", {
            "tenant": tenant.id, "version": tenant.row_version,
            "location": location.id, "location_version": location.row_version,
            "state": "active", "at": self.at.isoformat(),
        })

    def _pk(self) -> str:
        repo = SQLPK456Repository(self.session)
        authority = PK456Authority(repo)
        template = repo.template_version(
            self.scope.template_code, self.scope.template_version
        )
        if not template or not _SHA.fullmatch(str(template["template_sha256"])):
            raise SWESAustinReadinessHold("HOLD_PK_TEMPLATE_MISSING")
        root = _one_or_none(self.session, """
            SELECT lifecycle FROM public.pk_templates
             WHERE template_code=:code
        """, {"code": self.scope.template_code})
        if not root or root["lifecycle"] != "active":
            raise SWESAustinReadinessHold("HOLD_PK_TEMPLATE_NOT_ACTIVE")
        state = repo.tenant_template(
            self.scope.tenant_id, self.scope.template_code
        )
        if (
            state is None
            or state.version != self.scope.template_version
            or state.template_sha256 != template["template_sha256"]
        ):
            raise SWESAustinReadinessHold("HOLD_PK_BINDING_NOT_PINNED")
        applied = _one_or_none(self.session, """
            SELECT applied_plan_sha256, row_version
              FROM public.pk_tenant_template_bindings
             WHERE tenant_id=:tenant AND template_id=:template
        """, {"tenant": self.scope.tenant_id, "template": template["template_id"]})
        plan = authority.plan_application(PlanTemplateApplication(
            self.scope.tenant_id, self.scope.template_code,
            self.scope.template_version,
            repo.selected_optional_packs(self.scope.tenant_id, self.scope.template_code),
            dict(state.overrides),
        ))
        if (
            not applied or
            not _SHA.fullmatch(str(applied["applied_plan_sha256"])) or
            applied["applied_plan_sha256"] != plan.plan_sha256 or
            plan.conflicts or any(
                action not in {
                    "expose_xa_composition_metadata",
                    "resolve_pc4_configuration_defaults_via_public_contract",
                }
                for action in plan.actions
            )
        ):
            raise SWESAustinReadinessHold("HOLD_PK_PLAN_OR_ACTIONS_UNRESOLVED")
        for spec in (*plan.required_packs, *plan.optional_packs):
            code, version = spec.rsplit("@", 1)
            installation = repo.pack_installation(self.scope.tenant_id, code)
            if (
                not repo.is_certified(code, version)
                or installation is None
                or installation["version"] != version
                or installation["status"] != "active"
            ):
                raise SWESAustinReadinessHold("HOLD_PK_PACK_CERT_OR_ACTIVATION")
        config_evidence = self._verify_template_configuration(template, dict(state.overrides))
        return _reference("pk456", {
            "tenant": self.scope.tenant_id,
            "version": self.scope.template_version,
            "template_sha256": template["template_sha256"],
            "plan_sha256": plan.plan_sha256,
            "binding_version": applied["row_version"],
            "packs": list((*plan.required_packs, *plan.optional_packs)),
            "advisory_actions": list(plan.actions),
            "tenant_pc4_configuration_ref": config_evidence,
        })

    def _verify_template_configuration(self, template: Mapping, overrides: Mapping) -> str:
        """Read canonical PC4 configuration; a PK action alone is not proof."""
        defaults = template.get("configuration_defaults")
        if not isinstance(defaults, dict):
            raise SWESAustinReadinessHold("HOLD_PK_CONFIGURATION_INVALID")
        merged = json.loads(json.dumps(defaults))
        for path, value in sorted(overrides.items()):
            cursor = merged
            pieces = path.split(".")
            for name in pieces[:-1]:
                if not isinstance(cursor, dict) or name not in cursor:
                    raise SWESAustinReadinessHold("HOLD_PK_OVERRIDE_PATH_NOT_RESOLVED")
                cursor = cursor[name]
            if not isinstance(cursor, dict) or pieces[-1] not in cursor:
                raise SWESAustinReadinessHold("HOLD_PK_OVERRIDE_PATH_NOT_RESOLVED")
            cursor[pieces[-1]] = value

        def leaves(node: Mapping, prefix: str = ""):
            for key, value in sorted(node.items()):
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    yield from leaves(value, path)
                else:
                    yield path, value

        operating = OperatingContextAuthority(
            SQLOperatingContextRepository(self.session)
        )
        versions = []
        for key, value in leaves(merged):
            result = operating.resolve(
                tenant_id=self.scope.tenant_id, key=key,
                as_of=self.at, location_id=self.scope.location_id,
            )
            if (
                result is None or result.scope is not ConfigScope.TENANT
                or result.scope_id != self.scope.tenant_id
                or result.version < 1 or result.value != value
            ):
                raise SWESAustinReadinessHold("HOLD_PC4_TEMPLATE_CONFIGURATION_UNRESOLVED")
            versions.append((key, result.version, result.effective_from.isoformat()))
        return _reference("pc4-configuration", {
            "tenant_id": self.scope.tenant_id, "resolved": versions,
        })

    def _pc4(self, entitlement_codes: tuple[str, ...]) -> str:
        expected = tuple(sorted(set(entitlement_codes)))
        if (
            not expected or tuple(entitlement_codes) != expected
            or set(expected) != set(self.scope.entitlement_modules)
        ):
            raise SWESAustinReadinessHold("HOLD_PC4_ENTITLEMENT_SET_MISMATCH")
        repo = SQLOperatingContextRepository(self.session)
        contexts: dict[str, tuple[bool, bool, bool, bool]] = {}
        for capability in expected:
            module = self.scope.entitlement_modules[capability]
            owner = _one_or_none(self.session, """
                SELECT module_code, module_version, status
                  FROM public.core_modules
                 WHERE module_code=:module AND :capability=ANY(capabilities)
            """, {"module": module, "capability": capability})
            if not owner or owner["status"] != "available":
                raise SWESAustinReadinessHold("HOLD_PC4_MODULE_CAPABILITY_UNAVAILABLE")
            context = repo.capability_context(
                self.scope.tenant_id, module, capability, self.at
            )
            truths = (
                context.module_available, context.module_enabled,
                context.entitled, context.feature_active
            )
            if not all(truths):
                raise SWESAustinReadinessHold("HOLD_PC4_EFFECTIVE_CAPABILITY_DENIED")
            # A permissive effective row is insufficient if an overlapping
            # explicit disabled flag exists for the same tenant or globally.
            conflict = self.session.execute(text("""
                SELECT EXISTS(
                    SELECT 1 FROM public.feature_flags
                     WHERE (tenant_id=:tenant OR tenant_id IS NULL)
                       AND flag_code=:capability AND enabled=false
                       AND effective_from<=:at
                       AND (effective_to IS NULL OR effective_to>:at)
                )
            """), {"tenant": self.scope.tenant_id,
                   "capability": capability, "at": self.at}).scalar_one()
            if conflict:
                raise SWESAustinReadinessHold("HOLD_PC4_CONFLICTING_FEATURE_FLAG")
            disabled_module = self.session.execute(text("""
                SELECT EXISTS(
                    SELECT 1 FROM public.tenant_module_enablements
                     WHERE tenant_id=:tenant AND module_code=:module
                       AND enabled=false AND effective_from<=:at
                       AND (effective_to IS NULL OR effective_to>:at)
                )
            """), {"tenant": self.scope.tenant_id, "module": module,
                   "at": self.at}).scalar_one()
            if disabled_module:
                raise SWESAustinReadinessHold("HOLD_PC4_CONFLICTING_MODULE_ENABLEMENT")
            contexts[capability] = truths
        return _reference("pc4", {
            "tenant": self.scope.tenant_id,
            "capabilities": sorted((k, self.scope.entitlement_modules[k])
                                   for k in contexts),
            "effective_at": self.at.isoformat(),
            "all_four_controls": True,
        })

    def _pc5(self) -> str:
        session_id = self.scope.pc5_session_public_id
        capability = self.scope.pc5_capability_code
        permission = self.scope.pc5_permission_code
        role_code = self.scope.pc5_admin_role_code
        if (
            session_id is None or not permission or not capability
            or not role_code or not _CODE.fullmatch(role_code)
            or capability not in self.scope.entitlement_modules
        ):
            raise SWESAustinReadinessHold("HOLD_PC5_OPERATOR_OR_PERMISSION_UNSPECIFIED")
        repo4 = SQLOperatingContextRepository(self.session)
        ctx = repo4.capability_context(
            self.scope.tenant_id,
            self.scope.entitlement_modules[capability],
            capability, self.at
        )
        request = AuthorizationRequest(
            session_id=session_id,
            permission_code=permission,
            tenant_id=self.scope.tenant_id,
            target_scope=StructuralScope(ScopeType.TENANT, self.scope.tenant_id),
            resource_type="tenant",
            resource_id="swes-wnd-austin-virtual",
            occurred_at=self.at,
            module_available=ctx.module_available,
            module_enabled=ctx.module_enabled,
            entitled=ctx.entitled,
            feature_active=ctx.feature_active,
        )
        security = SecurityAuthority(SQLSecurityRepository(self.session))
        session = security.repository.session(session_id)
        if session is None or session.actor_type is not ActorType.HUMAN:
            raise SWESAustinReadinessHold("HOLD_PC5_NO_AUTHENTICATED_HUMAN_SESSION")
        # Permission ALLOW alone does not prove the tenant-admin role.
        admin_role = _one_or_none(self.session, """
            SELECT r.role_code
              FROM public.scoped_role_assignments a
              JOIN public.authorization_roles r ON r.id=a.role_id
             WHERE a.principal_id=:principal
               AND a.actor_type='human' AND a.tenant_id=:tenant
               AND a.scope_type='tenant' AND a.scope_id=:tenant
               AND a.status='active' AND r.status='active'
               AND r.role_code=:role
               AND (r.tenant_id=:tenant OR r.tenant_id IS NULL)
               AND a.valid_from<=:at
               AND (a.valid_to IS NULL OR a.valid_to>:at)
        """, {"principal": session.identity_id, "role": role_code,
               "tenant": self.scope.tenant_id, "at": self.at})
        if admin_role is None:
            raise SWESAustinReadinessHold("HOLD_PC5_TENANT_ADMIN_ROLE_NOT_ESTABLISHED")
        outcome = security.authorize(request)
        if outcome.decision is not Decision.ALLOW:
            raise SWESAustinReadinessHold("HOLD_PC5_AUTHORIZATION_NOT_ALLOW")
        return _reference("pc5", {
            "tenant": self.scope.tenant_id,
            "permission": permission, "role": role_code,
            "scope": "tenant",
            "decision": outcome.decision.value,
            "assurance": outcome.required_assurance,
            "at": self.at.isoformat(),
        })
