"""PA0-PA3 platform-administration orchestration without duplicating PC/PK authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Protocol

from .contracts import *

_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9.-]+)?$")
_PERIOD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_REQUIRED_READINESS = (
    "pc1_tenant_available",
    "pk_template_pinned",
    "pc4_entitlements_effective",
    "pc5_tenant_admin_ready",
)
_SECRET_KEYS = {"password", "api_key", "access_token", "secret", "secret_value", "private_key", "client_secret", "credential"}


class PlatformAdministrationError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


def _primitive(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
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


def _fingerprint(kind: str, value: Any) -> str:
    return hashlib.sha256((kind + "\0" + _canonical(value)).encode("utf-8")).hexdigest()


def _token(value: str, field: str) -> str:
    selected = str(value).strip().lower()
    if not _TOKEN.fullmatch(selected):
        raise PlatformAdministrationError("PA_INVALID_TOKEN", field)
    return selected


def _version(value: str) -> str:
    selected = str(value).strip()
    if not _VERSION.fullmatch(selected):
        raise PlatformAdministrationError("PA_INVALID_VERSION", selected)
    return selected


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PlatformAdministrationError("PA_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _positive_decimal(value: Any) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PlatformAdministrationError("PA_INVALID_QUANTITY") from exc
    if not selected.is_finite() or selected <= 0:
        raise PlatformAdministrationError("PA_INVALID_QUANTITY")
    return selected


def _safe_metadata(value: Any, path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            low = str(key).lower()
            if low in _SECRET_KEYS or low.endswith("_password") or low.endswith("_secret"):
                raise PlatformAdministrationError("PA_SECRET_MATERIAL_FORBIDDEN", f"{path}.{key}")
            _safe_metadata(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _safe_metadata(item, f"{path}[{index}]")


class TenantGateway(Protocol):
    def tenant_lifecycle(self, tenant_id: int) -> str | None: ...


class ReadinessGateway(Protocol):
    def assess(self, *, tenant_id: int, template_code: str, template_version: str, entitlement_codes: tuple[str, ...]) -> dict[str, tuple[str, str]]: ...


class PlatformAdministrationAuthority:
    """Administrative truth plus orchestration references; PC1/PC4/PC5/PK stay authoritative."""

    def __init__(self, repository, tenant_gateway: TenantGateway, readiness_gateway: ReadinessGateway):
        self.repository = repository
        self.tenant_gateway = tenant_gateway
        self.readiness_gateway = readiness_gateway

    def register_merchant(self, command: RegisterMerchant) -> MerchantAdministrationRecord:
        self._tenant_available(command.tenant_id)
        external = str(command.external_reference).strip() if command.external_reference else None
        normalized = RegisterMerchant(str(command.command_key).strip(), command.tenant_id, external)
        if not normalized.command_key:
            raise PlatformAdministrationError("PA_COMMAND_KEY_REQUIRED")
        return self.repository.register_merchant(normalized, _fingerprint("register_merchant", normalized))

    def transition_merchant(self, command: TransitionMerchant) -> MerchantAdministrationRecord:
        self._tenant_available(command.tenant_id, allow_suspended=True)
        reason = str(command.reason).strip()
        if not reason:
            raise PlatformAdministrationError("PA_REASON_REQUIRED")
        current = self.repository.merchant(command.tenant_id)
        if current is None:
            raise PlatformAdministrationError("PA_MERCHANT_NOT_FOUND")
        allowed = {
            MerchantAdministrationState.REGISTERED: set(),
            MerchantAdministrationState.ONBOARDING: set(),
            MerchantAdministrationState.READY: {MerchantAdministrationState.OPERATIONAL, MerchantAdministrationState.OFFBOARDING},
            MerchantAdministrationState.OPERATIONAL: {MerchantAdministrationState.OFFBOARDING},
            MerchantAdministrationState.OFFBOARDING: {MerchantAdministrationState.CLOSED},
            MerchantAdministrationState.CLOSED: set(),
        }
        target = MerchantAdministrationState(command.target)
        if target not in allowed[current.state]:
            raise PlatformAdministrationError("PA_INVALID_MERCHANT_TRANSITION")
        if target is MerchantAdministrationState.OPERATIONAL:
            onboarding = self.repository.onboarding(command.tenant_id)
            if onboarding is None or onboarding.status is not OnboardingStatus.COMPLETED:
                raise PlatformAdministrationError("PA_ONBOARDING_NOT_COMPLETE")
        normalized = TransitionMerchant(command.command_key, command.tenant_id, target, command.expected_row_version, reason)
        return self.repository.transition_merchant(normalized, _fingerprint("transition_merchant", normalized))

    def register_plan(self, command: RegisterPlanVersion) -> PlanVersionRecord:
        plan = command.plan
        code = _token(plan.plan_code, "plan_code")
        owner = _token(plan.owner_code, "owner_code")
        version = _version(plan.version)
        entitlements = tuple(sorted({_token(x, "entitlement_code") for x in plan.entitlement_codes}))
        quotas: list[PlanQuota] = []
        seen: set[str] = set()
        for quota in plan.quotas:
            meter = _token(quota.meter_code, "meter_code")
            if meter in seen:
                raise PlatformAdministrationError("PA_DUPLICATE_QUOTA", meter)
            seen.add(meter)
            quotas.append(PlanQuota(meter, _positive_decimal(quota.limit)))
        _safe_metadata(plan.metadata, "plan.metadata")
        normalized_plan = PlanDefinition(code, version, owner, entitlements, tuple(sorted(quotas, key=lambda q: q.meter_code)), dict(plan.metadata))
        normalized = RegisterPlanVersion(str(command.command_key).strip(), normalized_plan)
        if not normalized.command_key:
            raise PlatformAdministrationError("PA_COMMAND_KEY_REQUIRED")
        canonical = _canonical(normalized_plan)
        return self.repository.register_plan(normalized, _fingerprint("register_plan", normalized_plan), canonical, hashlib.sha256(canonical.encode()).hexdigest())

    def start_subscription(self, command: StartSubscription) -> SubscriptionRecord:
        self._tenant_available(command.tenant_id)
        if self.repository.merchant(command.tenant_id) is None:
            raise PlatformAdministrationError("PA_MERCHANT_NOT_FOUND")
        code = _token(command.plan_code, "plan_code")
        version = _version(command.version)
        if self.repository.plan(code, version) is None:
            raise PlatformAdministrationError("PA_PLAN_VERSION_NOT_FOUND")
        start = _aware(command.starts_at)
        end = _aware(command.ends_at) if command.ends_at else None
        if end and end <= start:
            raise PlatformAdministrationError("PA_INVALID_SUBSCRIPTION_PERIOD")
        normalized = StartSubscription(command.command_key, command.tenant_id, code, version, start, end)
        return self.repository.start_subscription(normalized, _fingerprint("start_subscription", normalized))

    def transition_subscription(self, command: TransitionSubscription) -> SubscriptionRecord:
        reason = str(command.reason).strip()
        if not reason:
            raise PlatformAdministrationError("PA_REASON_REQUIRED")
        current = self.repository.subscription(command.tenant_id)
        if current is None:
            raise PlatformAdministrationError("PA_SUBSCRIPTION_NOT_FOUND")
        target = SubscriptionStatus(command.target)
        allowed = {
            SubscriptionStatus.PENDING: {SubscriptionStatus.ACTIVE, SubscriptionStatus.ENDED},
            SubscriptionStatus.ACTIVE: {SubscriptionStatus.PAUSED, SubscriptionStatus.ENDED},
            SubscriptionStatus.PAUSED: {SubscriptionStatus.ACTIVE, SubscriptionStatus.ENDED},
            SubscriptionStatus.ENDED: set(),
        }
        if target not in allowed[current.status]:
            raise PlatformAdministrationError("PA_INVALID_SUBSCRIPTION_TRANSITION")
        normalized = TransitionSubscription(command.command_key, command.tenant_id, target, command.expected_row_version, reason)
        return self.repository.transition_subscription(normalized, _fingerprint("transition_subscription", normalized))

    def commercial_entitlement_projection(self, tenant_id: int) -> tuple[str, ...]:
        """Desired commercial grant only. Effective runtime entitlement truth remains PC4."""
        subscription = self.repository.subscription(tenant_id)
        if subscription is None or subscription.status is not SubscriptionStatus.ACTIVE:
            return ()
        return subscription.entitlement_projection

    def record_usage(self, command: RecordUsage) -> UsageRecord:
        subscription = self.repository.subscription(command.tenant_id)
        if subscription is None or subscription.status is not SubscriptionStatus.ACTIVE:
            raise PlatformAdministrationError("PA_ACTIVE_SUBSCRIPTION_REQUIRED")
        meter = _token(command.meter_code, "meter_code")
        period = str(command.period_key).strip()
        if not _PERIOD.fullmatch(period):
            raise PlatformAdministrationError("PA_INVALID_PERIOD_KEY")
        quotas = {q.meter_code: q.limit for q in self.repository.plan_quotas(subscription.plan_code, subscription.version)}
        if meter not in quotas:
            raise PlatformAdministrationError("PA_METER_NOT_DECLARED_BY_PLAN", meter)
        event_key = str(command.event_key).strip()
        source = str(command.source_reference).strip()
        if not event_key or not source:
            raise PlatformAdministrationError("PA_USAGE_IDENTITY_REQUIRED")
        _safe_metadata(command.metadata, "usage.metadata")
        normalized = RecordUsage(command.command_key, command.tenant_id, event_key, meter, _positive_decimal(command.quantity), period, _aware(command.occurred_at), source, dict(command.metadata))
        return self.repository.record_usage(normalized, _fingerprint("record_usage", normalized))

    def quota_status(self, tenant_id: int, meter_code: str, period_key: str) -> QuotaStatus:
        subscription = self.repository.subscription(tenant_id)
        if subscription is None:
            raise PlatformAdministrationError("PA_SUBSCRIPTION_NOT_FOUND")
        meter = _token(meter_code, "meter_code")
        quotas = {q.meter_code: q.limit for q in self.repository.plan_quotas(subscription.plan_code, subscription.version)}
        limit = quotas.get(meter)
        used = self.repository.usage_total(tenant_id, meter, str(period_key))
        return QuotaStatus(tenant_id, meter, str(period_key), used, limit, bool(limit is not None and used > limit))

    def start_onboarding(self, command: StartOnboarding) -> OnboardingRecord:
        self._tenant_available(command.tenant_id)
        merchant = self.repository.merchant(command.tenant_id)
        if merchant is None:
            raise PlatformAdministrationError("PA_MERCHANT_NOT_FOUND")
        if merchant.state is not MerchantAdministrationState.REGISTERED:
            raise PlatformAdministrationError("PA_MERCHANT_NOT_REGISTERED")
        subscription = self.repository.subscription(command.tenant_id)
        if subscription is None or subscription.status is not SubscriptionStatus.ACTIVE:
            raise PlatformAdministrationError("PA_ACTIVE_SUBSCRIPTION_REQUIRED")
        if (subscription.plan_code, subscription.version) != (_token(command.plan_code, "plan_code"), _version(command.plan_version)):
            raise PlatformAdministrationError("PA_ONBOARDING_PLAN_MISMATCH")
        normalized = StartOnboarding(command.command_key, command.tenant_id, _token(command.template_code, "template_code"), _version(command.template_version), subscription.plan_code, subscription.version)
        return self.repository.start_onboarding(normalized, _fingerprint("start_onboarding", normalized))

    def evaluate_readiness(self, command: EvaluateReadiness) -> OnboardingRecord:
        current = self.repository.onboarding(command.tenant_id)
        if current is None:
            raise PlatformAdministrationError("PA_ONBOARDING_NOT_FOUND")
        subscription = self.repository.subscription(command.tenant_id)
        if subscription is None or subscription.status is not SubscriptionStatus.ACTIVE:
            raise PlatformAdministrationError("PA_ACTIVE_SUBSCRIPTION_REQUIRED")
        projection = subscription.entitlement_projection
        raw = self.readiness_gateway.assess(tenant_id=command.tenant_id, template_code=current.template_code, template_version=current.template_version, entitlement_codes=projection)
        if set(raw) != set(_REQUIRED_READINESS):
            raise PlatformAdministrationError("PA_READINESS_CHECK_COVERAGE")
        checks = tuple(ReadinessCheck(code, ReadinessStatus(raw[code][0]), str(raw[code][1]).strip()) for code in _REQUIRED_READINESS)
        if any(not item.evidence_reference for item in checks):
            raise PlatformAdministrationError("PA_READINESS_EVIDENCE_REQUIRED")
        readiness_sha = hashlib.sha256(_canonical(checks).encode()).hexdigest()
        normalized = EvaluateReadiness(command.command_key, command.tenant_id, command.expected_row_version)
        return self.repository.evaluate_readiness(normalized, _fingerprint("evaluate_readiness", {"command": normalized, "checks": checks}), checks, readiness_sha)

    def complete_onboarding(self, command: CompleteOnboarding) -> OnboardingRecord:
        current = self.repository.onboarding(command.tenant_id)
        if current is None:
            raise PlatformAdministrationError("PA_ONBOARDING_NOT_FOUND")
        if current.status is not OnboardingStatus.READY:
            raise PlatformAdministrationError("PA_ONBOARDING_NOT_READY")
        normalized = CompleteOnboarding(command.command_key, command.tenant_id, command.expected_row_version)
        return self.repository.complete_onboarding(normalized, _fingerprint("complete_onboarding", normalized))

    def _tenant_available(self, tenant_id: int, allow_suspended: bool = False) -> str:
        lifecycle = self.tenant_gateway.tenant_lifecycle(tenant_id)
        if lifecycle is None:
            raise PlatformAdministrationError("PA_TENANT_NOT_FOUND")
        if lifecycle == "retired" or (lifecycle == "suspended" and not allow_suspended):
            raise PlatformAdministrationError("PA_TENANT_UNAVAILABLE")
        return lifecycle
