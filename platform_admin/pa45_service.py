"""PA4-PA5 support/recovery and derived health authority.

PA45 records platform-administration evidence.  PC5 remains authorization truth;
health observations never become operational or financial source truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from .pa45_contracts import *

_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_SECRET_KEYS = {"password", "api_key", "access_token", "secret", "secret_value", "private_key", "client_secret", "credential"}
_MAX_DELEGATED = timedelta(hours=8)
_MAX_BREAK_GLASS = timedelta(hours=1)
_HEALTH_RANK = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.BLOCKED: 3,
}


class PA45AuthorityError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


def _primitive(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
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
        raise PA45AuthorityError("PA45_INVALID_TOKEN", field)
    return selected


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PA45AuthorityError("PA45_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _required(value: Any, code: str) -> str:
    selected = str(value).strip()
    if not selected:
        raise PA45AuthorityError(code)
    return selected


def _safe_metadata(value: Any, path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            low = str(key).lower()
            if low in _SECRET_KEYS or low.endswith("_password") or low.endswith("_secret"):
                raise PA45AuthorityError("PA45_SECRET_MATERIAL_FORBIDDEN", f"{path}.{key}")
            _safe_metadata(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _safe_metadata(item, f"{path}[{index}]")


class SupportAuthorizationGateway(Protocol):
    def authorize_support(
        self,
        *,
        tenant_id: int,
        actor_identity_id: UUID,
        scopes: tuple[str, ...],
        access_mode: str,
        authorization_reference: str,
        step_up_reference: str | None,
    ) -> tuple[bool, str]: ...


class HealthGateway(Protocol):
    def assess_merchant(self, *, tenant_id: int) -> dict[str, tuple[str, str, datetime]]: ...
    def assess_platform(self) -> dict[str, tuple[str, str, datetime]]: ...


class PA45Authority:
    """PA4-PA5 authority; support evidence and health snapshots only."""

    def __init__(self, repository, security_gateway: SupportAuthorizationGateway, health_gateway: HealthGateway, now_provider=None):
        self.repository = repository
        self.security_gateway = security_gateway
        self.health_gateway = health_gateway
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def open_support_session(self, command: OpenSupportSession) -> SupportSessionRecord:
        if not self.repository.merchant_exists(command.tenant_id):
            raise PA45AuthorityError("PA45_MERCHANT_NOT_FOUND")
        actor = UUID(str(command.actor_identity_id))
        mode = SupportAccessMode(command.access_mode)
        scopes = tuple(sorted({_token(value, "scope") for value in command.scopes}))
        if not scopes:
            raise PA45AuthorityError("PA45_SUPPORT_SCOPE_REQUIRED")
        reason = _required(command.reason, "PA45_REASON_REQUIRED")
        authorization = _required(command.authorization_reference, "PA45_AUTHORIZATION_REFERENCE_REQUIRED")
        start = _aware(command.starts_at)
        expiry = _aware(command.expires_at)
        if expiry <= start:
            raise PA45AuthorityError("PA45_INVALID_SUPPORT_PERIOD")
        duration = expiry - start
        step_up = str(command.step_up_reference).strip() if command.step_up_reference else None
        break_glass_evidence = str(command.break_glass_evidence_reference).strip() if command.break_glass_evidence_reference else None
        if mode is SupportAccessMode.BREAK_GLASS:
            if duration > _MAX_BREAK_GLASS:
                raise PA45AuthorityError("PA45_BREAK_GLASS_DURATION_EXCEEDED")
            if not step_up or not break_glass_evidence:
                raise PA45AuthorityError("PA45_BREAK_GLASS_EVIDENCE_REQUIRED")
        elif duration > _MAX_DELEGATED:
            raise PA45AuthorityError("PA45_DELEGATED_DURATION_EXCEEDED")
        _safe_metadata(command.metadata, "support.metadata")
        allowed, evidence = self.security_gateway.authorize_support(
            tenant_id=command.tenant_id,
            actor_identity_id=actor,
            scopes=scopes,
            access_mode=mode.value,
            authorization_reference=authorization,
            step_up_reference=step_up,
        )
        if not allowed:
            raise PA45AuthorityError("PA45_SUPPORT_NOT_AUTHORIZED")
        evidence = _required(evidence, "PA45_AUTHORIZATION_EVIDENCE_REQUIRED")
        normalized = OpenSupportSession(
            str(command.command_key).strip(), command.tenant_id, actor, mode, scopes, reason,
            start, expiry, authorization, step_up, break_glass_evidence,
            {**dict(command.metadata), "authorization_evidence_reference": evidence},
        )
        if not normalized.command_key:
            raise PA45AuthorityError("PA45_COMMAND_KEY_REQUIRED")
        return self.repository.open_support_session(normalized, _fingerprint("open_support_session", normalized))

    def transition_support_session(self, command: TransitionSupportSession) -> SupportSessionRecord:
        current = self.repository.support_session(command.tenant_id, command.support_session_id)
        if current is None:
            raise PA45AuthorityError("PA45_SUPPORT_SESSION_NOT_FOUND")
        target = SupportSessionState(command.target)
        if current.state is not SupportSessionState.ACTIVE or target not in {SupportSessionState.CLOSED, SupportSessionState.REVOKED}:
            raise PA45AuthorityError("PA45_INVALID_SUPPORT_TRANSITION")
        reason = _required(command.reason, "PA45_REASON_REQUIRED")
        normalized = TransitionSupportSession(command.command_key, command.tenant_id, UUID(str(command.support_session_id)), target, command.expected_row_version, reason)
        return self.repository.transition_support_session(normalized, _fingerprint("transition_support_session", normalized))

    def record_support_action(self, command: RecordSupportAction) -> SupportActionRecord:
        session = self._active_support_session(command.tenant_id, command.support_session_id, _aware(command.occurred_at))
        action = _token(command.action_code, "action_code")
        target = _required(command.target_reference, "PA45_TARGET_REFERENCE_REQUIRED")
        evidence = _required(command.evidence_reference, "PA45_EVIDENCE_REQUIRED")
        _safe_metadata(command.metadata, "support_action.metadata")
        normalized = RecordSupportAction(command.command_key, command.tenant_id, session.public_id, action, target, evidence, _aware(command.occurred_at), dict(command.metadata))
        return self.repository.record_support_action(normalized, _fingerprint("record_support_action", normalized))

    def open_recovery_case(self, command: OpenRecoveryCase) -> RecoveryCaseRecord:
        if not self.repository.merchant_exists(command.tenant_id):
            raise PA45AuthorityError("PA45_MERCHANT_NOT_FOUND")
        normalized = OpenRecoveryCase(
            str(command.command_key).strip(), command.tenant_id,
            _required(command.case_key, "PA45_RECOVERY_CASE_KEY_REQUIRED"),
            _token(command.problem_code, "problem_code"),
            _required(command.subject_reference, "PA45_SUBJECT_REFERENCE_REQUIRED"),
            _required(command.reason, "PA45_REASON_REQUIRED"),
            UUID(str(command.opened_by_identity_id)),
            _required(command.evidence_reference, "PA45_EVIDENCE_REQUIRED"),
        )
        if not normalized.command_key:
            raise PA45AuthorityError("PA45_COMMAND_KEY_REQUIRED")
        return self.repository.open_recovery_case(normalized, _fingerprint("open_recovery_case", normalized))

    def record_recovery_action(self, command: RecordRecoveryAction) -> RecoveryActionRecord:
        case = self.repository.recovery_case(command.tenant_id, command.recovery_case_id)
        if case is None:
            raise PA45AuthorityError("PA45_RECOVERY_CASE_NOT_FOUND")
        if case.state is not RecoveryCaseState.OPEN:
            raise PA45AuthorityError("PA45_RECOVERY_CASE_NOT_OPEN")
        when = _aware(command.occurred_at)
        support_id = UUID(str(command.support_session_id)) if command.support_session_id else None
        if support_id is not None:
            self._active_support_session(command.tenant_id, support_id, when)
        _safe_metadata(command.metadata, "recovery_action.metadata")
        normalized = RecordRecoveryAction(
            command.command_key, command.tenant_id, case.public_id,
            _token(command.action_code, "action_code"), RecoveryActionOutcome(command.outcome),
            _required(command.evidence_reference, "PA45_EVIDENCE_REQUIRED"), when, support_id, dict(command.metadata),
        )
        return self.repository.record_recovery_action(normalized, _fingerprint("record_recovery_action", normalized))

    def transition_recovery_case(self, command: TransitionRecoveryCase) -> RecoveryCaseRecord:
        case = self.repository.recovery_case(command.tenant_id, command.recovery_case_id)
        if case is None:
            raise PA45AuthorityError("PA45_RECOVERY_CASE_NOT_FOUND")
        target = RecoveryCaseState(command.target)
        if case.state is not RecoveryCaseState.OPEN or target not in {RecoveryCaseState.RESOLVED, RecoveryCaseState.ABANDONED}:
            raise PA45AuthorityError("PA45_INVALID_RECOVERY_TRANSITION")
        normalized = TransitionRecoveryCase(
            command.command_key, command.tenant_id, case.public_id, target,
            command.expected_row_version, _required(command.reason, "PA45_REASON_REQUIRED"),
            _required(command.evidence_reference, "PA45_EVIDENCE_REQUIRED"),
        )
        return self.repository.transition_recovery_case(normalized, _fingerprint("transition_recovery_case", normalized))

    def capture_merchant_health(self, command: CaptureMerchantHealth) -> HealthSnapshotRecord:
        if not self.repository.merchant_exists(command.tenant_id):
            raise PA45AuthorityError("PA45_MERCHANT_NOT_FOUND")
        checks = self._health_checks(self.health_gateway.assess_merchant(tenant_id=command.tenant_id))
        fingerprint = _fingerprint("capture_merchant_health", {"command": command, "checks": checks})
        return self.repository.capture_health(command.command_key, fingerprint, "merchant", command.tenant_id, self._overall(checks), checks)

    def capture_platform_health(self, command: CapturePlatformHealth) -> HealthSnapshotRecord:
        checks = self._health_checks(self.health_gateway.assess_platform())
        fingerprint = _fingerprint("capture_platform_health", {"command": command, "checks": checks})
        return self.repository.capture_health(command.command_key, fingerprint, "platform", None, self._overall(checks), checks)

    def latest_merchant_health(self, tenant_id: int) -> HealthSnapshotRecord | None:
        return self.repository.latest_health("merchant", tenant_id)

    def latest_platform_health(self) -> HealthSnapshotRecord | None:
        return self.repository.latest_health("platform", None)

    def _active_support_session(self, tenant_id: int, public_id: UUID, occurred_at: datetime) -> SupportSessionRecord:
        session = self.repository.support_session(tenant_id, public_id)
        if session is None:
            raise PA45AuthorityError("PA45_SUPPORT_SESSION_NOT_FOUND")
        if session.state is not SupportSessionState.ACTIVE:
            raise PA45AuthorityError("PA45_SUPPORT_SESSION_INACTIVE")
        if occurred_at < session.starts_at or occurred_at >= session.expires_at:
            raise PA45AuthorityError("PA45_SUPPORT_SESSION_EXPIRED")
        return session

    def _health_checks(self, raw: dict[str, tuple[str, str, datetime]]) -> tuple[HealthCheck, ...]:
        if not isinstance(raw, dict) or not raw:
            raise PA45AuthorityError("PA45_HEALTH_CHECKS_REQUIRED")
        checks: list[HealthCheck] = []
        for code, value in sorted(raw.items()):
            if not isinstance(value, tuple) or len(value) != 3:
                raise PA45AuthorityError("PA45_HEALTH_CHECK_INVALID", str(code))
            status, evidence, observed = value
            checks.append(HealthCheck(_token(code, "health.check_code"), HealthStatus(status), _required(evidence, "PA45_HEALTH_EVIDENCE_REQUIRED"), _aware(observed)))
        return tuple(checks)

    @staticmethod
    def _overall(checks: tuple[HealthCheck, ...]) -> HealthStatus:
        return max((check.status for check in checks), key=lambda status: _HEALTH_RANK[status])
