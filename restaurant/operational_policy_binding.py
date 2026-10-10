"""Restaurant-owned operational policy composition over existing PK0123 + PC4.

The selected value is never inferred from tenant identity, route identity,
pack activation alone, or unrelated configuration. Read-only resolution.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.domain.operational_policy import NEUTRAL_POLICY, OperationalPolicy
from core.platform.operating_context import (
    ConfigScope, ConfigType, DefineConfiguration, OperatingContextAuthority,
)
from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
from pack_platform import PackAuthority
from pack_platform.contracts import PackStatus
from pack_platform.sql_repository import SQLPackRepository
from restaurant.wnd_operational_policy import WND_POLICY

PACK_CODE = "industry.restaurant"
SELECTOR_KEY = "restaurant.operational_policy.profile"
WND_PROFILE = "wnd.logpom"


class OperationalPolicyBindingError(RuntimeError):
    """A configured but unauthorized or unknown policy must never downgrade."""


def define_selector(operating: OperatingContextAuthority):
    """Idempotent PC4 declaration, without touching immutable PK 1.0.0."""
    return operating.define(DefineConfiguration(
        "n2-r1-define-restaurant-operational-policy-profile-v1",
        SELECTOR_KEY, ConfigType.CODE, "restaurant",
        (ConfigScope.TENANT,), (ConfigScope.TENANT,),
        required=False, secret=False, tenant_overridable=True,
        constraints={}, default_value=None,
    ))


def resolve_operational_policy(
    *,
    tenant_id: int,
    as_of: datetime,
    pack_authority: PackAuthority,
    operating_context: OperatingContextAuthority,
) -> OperationalPolicy:
    """Always read PC4 selector; only explicit WND value and PK ACTIVE grants WND."""
    if not isinstance(as_of, datetime) or not as_of.tzinfo or as_of.utcoffset() is None:
        raise OperationalPolicyBindingError("POLICY_EFFECTIVE_TIME_REQUIRED")
    if not isinstance(tenant_id, int) or tenant_id < 1:
        raise OperationalPolicyBindingError("POLICY_TENANT_REQUIRED")
    try:
        selected = operating_context.resolve(
            tenant_id=tenant_id, key=SELECTOR_KEY, as_of=as_of,
        )
    except Exception as exc:
        raise OperationalPolicyBindingError("POLICY_CONFIGURATION_UNAVAILABLE") from exc
    if selected is None:
        return NEUTRAL_POLICY
    if (selected.key != SELECTOR_KEY or selected.value_type != ConfigType.CODE
        or selected.scope != ConfigScope.TENANT or selected.scope_id != tenant_id):
        raise OperationalPolicyBindingError("POLICY_SCOPE_OR_TYPE_INVALID")
    if selected.value != WND_PROFILE:
        raise OperationalPolicyBindingError("POLICY_PROFILE_UNKNOWN")
    try:
        state = pack_authority.state(tenant_id, PACK_CODE)
    except Exception as exc:
        raise OperationalPolicyBindingError("POLICY_PACK_STATE_UNAVAILABLE") from exc
    if state is None or state.tenant_id != tenant_id or state.pack_code != PACK_CODE or state.status != PackStatus.ACTIVE:
        raise OperationalPolicyBindingError("POLICY_REQUIRED_PACK_INACTIVE")
    return WND_POLICY


def resolve_for_tenant(db, tenant_id: int, *, as_of: datetime | None = None):
    """Explicit adapter composition. Must be called from a trusted tenant context."""
    timestamp = as_of if as_of is not None else datetime.now(timezone.utc)
    return resolve_operational_policy(
        tenant_id=tenant_id,
        as_of=timestamp,
        pack_authority=PackAuthority(SQLPackRepository(db)),
        operating_context=OperatingContextAuthority(SQLOperatingContextRepository(db)),
    )
