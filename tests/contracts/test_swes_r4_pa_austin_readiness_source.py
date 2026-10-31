"""Fail-closed source qualification; no database credentials, fixtures or hosted records."""
from datetime import datetime, timezone
from uuid import UUID
import pytest

from platform_admin.swes_austin_readiness import (
    SWESAustinReadinessScope, SWESAustinReadinessHold,
    SWESAustinReadinessGateway,
    CHECKS,
)

NOW = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
CAP = {"restaurant.menu.read": "restaurant"}


def scope(**kwargs):
    d = dict(
        tenant_id=910001, tenant_code="SWES_WND_AUSTIN_TEST",
        currency="XAF", location_id=5,
        template_code="restaurant.counter_service", template_version="1.0.0",
        entitlement_modules=CAP,
        pc5_session_public_id=None, pc5_permission_code="pa.merchant.admin",
        pc5_capability_code="restaurant.menu.read",
        pc5_admin_role_code="swes_wnd_austin_admin",
    )
    d.update(kwargs)
    return SWESAustinReadinessScope(**d)


@pytest.mark.parametrize("override", [
    {"tenant_id": 2}, {"tenant_id": 910002},
    {"tenant_code": "wnd"}, {"currency": "USD"},
    {"location_id": 1}, {"location_id": 6}
])
def test_wrong_tenant_and_staging_target_deny_before_db(override):
    with pytest.raises(SWESAustinReadinessHold, match="HOLD_TARGET_NOT_SWES_AUSTIN_TEST"):
        scope(**override)


class ClosedSession:
    def execute(self, *_args, **_kwargs):
        raise PermissionError("simulated unavailable authority, not valid proof")


def test_absent_real_source_is_four_fail_not_pass():
    gateway = SWESAustinReadinessGateway(ClosedSession(), scope(), at=NOW)
    r = gateway.assess(
        tenant_id=910001,
        template_code="restaurant.counter_service",
        template_version="1.0.0",
        entitlement_codes=("restaurant.menu.read",),
    )
    assert set(r) == set(CHECKS)
    assert all(status == "fail" and ref.startswith(code + ":sha256:")
               for code, (status, ref) in r.items())
    assert gateway.details["pc5_tenant_admin_ready"] == "HOLD_PC5_OPERATOR_OR_PERMISSION_UNSPECIFIED"
    assert set(gateway.details[c] for c in CHECKS[:3]) == {"HOLD_SOURCE_UNAVAILABLE"}


def test_mismatch_fails_before_source_read():
    gateway = SWESAustinReadinessGateway(ClosedSession(), scope(), at=NOW)
    with pytest.raises(SWESAustinReadinessHold, match="HOLD_READINESS_SCOPE_MISMATCH"):
        gateway.assess(tenant_id=2, template_code="restaurant.counter_service",
                       template_version="1.0.0", entitlement_codes=("restaurant.menu.read",))


def test_pc5_no_session_is_not_synthetic_authorization():
    gateway = SWESAustinReadinessGateway(ClosedSession(), scope(), at=NOW)
    with pytest.raises(SWESAustinReadinessHold, match="HOLD_PC5_OPERATOR_OR_PERMISSION_UNSPECIFIED"):
        gateway._pc5()


def test_explicit_source_only_scope_is_not_credential_or_signature():
    from platform_admin.swes_austin_readiness import _reference
    ref = _reference("pc1", {"tenant": 910001, "state": "active"})
    assert ref.startswith("pc1:sha256:")
    assert "910001" not in ref


def test_pk_template_override_absent_from_defaults_fails_closed():
    gateway = SWESAustinReadinessGateway(ClosedSession(), scope(), at=NOW)
    with pytest.raises(SWESAustinReadinessHold, match="HOLD_PK_OVERRIDE_PATH_NOT_RESOLVED"):
        gateway._verify_template_configuration(
            {"configuration_defaults": {"restaurant": {"tables": {"enabled": False}}}},
            {"restaurant.tables.fake": True},
        )


def test_pk_template_configuration_requires_actual_tenant_scoped_pc4(monkeypatch):
    from types import SimpleNamespace
    from platform_admin import swes_austin_readiness as module

    class WrongScope:
        def __init__(self, _repository):
            pass
        def resolve(self, **_kwargs):
            return SimpleNamespace(scope=module.ConfigScope.PLATFORM, scope_id=None,
                                   version=1, value=False, effective_from=NOW)

    monkeypatch.setattr(module, "OperatingContextAuthority", WrongScope)
    monkeypatch.setattr(module, "SQLOperatingContextRepository", lambda _session: None)
    gateway = SWESAustinReadinessGateway(ClosedSession(), scope(), at=NOW)
    with pytest.raises(SWESAustinReadinessHold, match="HOLD_PC4_TEMPLATE_CONFIGURATION_UNRESOLVED"):
        gateway._verify_template_configuration(
            {"configuration_defaults": {"restaurant": {"tables": {"enabled": False}}}},
            {},
        )
