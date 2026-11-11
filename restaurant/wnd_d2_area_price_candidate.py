"""W-only, additive, nonoperative restaurant area / VIP price consumer.

A merchant config/seat lookup and SO1 price authority are injected by trusted
server owners. Neither caller-selected price codes nor client-supplied totals
are accepted. This module has NO route, DB writer, pack installer, or payment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable
from uuid import UUID

from shared_operations.so1.contracts import Price, ResolvePrice, ScopeType, TargetType


class WAreaError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AreaConfiguration:
    tenant_id: int
    location_id: int
    area_code: str
    price_code: str
    allowed_tables: tuple[str, ...] = ()
    revision: int = 1
    active: bool = True


@dataclass(frozen=True)
class VenueConfiguration:
    tenant_id: int
    location_id: int
    revision: int
    areas: tuple[AreaConfiguration, ...]
    table_service_enabled: bool
    xafchat_qr_enabled: bool
    restaurant_pack_active: bool
    pc4_capability_effective: bool
    pc5_permission_effective: bool


@dataclass(frozen=True)
class VerifiedOrderPlacement:
    """Data returned by a trusted SERVER-owned order/seat binding port, not JSON."""
    order_public_id: UUID
    tenant_id: int
    location_id: int
    area_code: str
    area_revision: int
    table_code: str | None
    channel: str  # pos or xafchat_qr


@dataclass(frozen=True)
class RestaurantPriceQuote:
    order_public_id: UUID
    tenant_id: int
    location_id: int
    area_code: str
    area_revision: int
    table_code: str | None
    price_code: str
    price_public_id: UUID
    price_version: int
    target_type: TargetType
    target_public_id: UUID   # same SKU/offer across normal and VIP
    whole_xaf: int
    currency: str
    channel: str
    venue_revision: int


def resolve_area_price(
    *,
    venue: VenueConfiguration,
    order_public_id: UUID,
    target_type: TargetType,
    target_public_id: UUID,
    effective_at: datetime,
    verified_placement_lookup: Callable[[int, int, UUID], VerifiedOrderPlacement | None],
    so1_price_resolver: Callable[[ResolvePrice], Price],
) -> RestaurantPriceQuote:
    """Fail-closed trust seam: SERVER seat resolver -> SERVER area -> SO1 winner.

    NOTE: PC1/PC4/PC5 provider authenticity is a prerequisite at composition
    and is NOT implemented or attested by these synthetic source booleans.
    No user-supplied area/price_code exists in this method signature.
    """
    if (type(venue.tenant_id) is not int or venue.tenant_id <= 0
            or type(venue.location_id) is not int or venue.location_id <= 0
            or type(venue.revision) is not int or venue.revision < 1):
        raise WAreaError("W_AREA_SCOPE_INVALID")
    if not all((venue.restaurant_pack_active,
                venue.pc4_capability_effective,
                venue.pc5_permission_effective)):
        raise WAreaError("W_AREA_EFFECTIVE_AUTHORITY_REQUIRED")
    if (not isinstance(effective_at, datetime) or effective_at.tzinfo is None
            or effective_at.utcoffset() is None):
        raise WAreaError("W_AREA_AWARE_TIME_REQUIRED")
    if not isinstance(order_public_id, UUID) or order_public_id.int == 0:
        raise WAreaError("W_AREA_ORDER_REQUIRED")
    if not isinstance(target_public_id, UUID) or target_public_id.int == 0:
        raise WAreaError("W_AREA_TARGET_REQUIRED")
    if not isinstance(target_type, TargetType):
        raise WAreaError("W_AREA_TARGET_TYPE_INVALID")

    areas = {}
    for a in venue.areas:
        if (a.tenant_id != venue.tenant_id or a.location_id != venue.location_id
                or not a.area_code or not a.price_code
                or type(a.revision) is not int or a.revision < 1
                or a.area_code in areas or len(a.allowed_tables) != len(set(a.allowed_tables))):
            raise WAreaError("W_AREA_CONFIG_INCONSISTENT")
        areas[a.area_code] = a

    try:
        placement = verified_placement_lookup(
            venue.tenant_id, venue.location_id, order_public_id
        )
    except Exception as exc:
        raise WAreaError("W_AREA_TRUSTED_LOOKUP_UNAVAILABLE") from exc
    if not isinstance(placement, VerifiedOrderPlacement):
        raise WAreaError("W_AREA_TRUSTED_BINDING_REQUIRED")
    if (placement.order_public_id != order_public_id or
            placement.tenant_id != venue.tenant_id or
            placement.location_id != venue.location_id):
        raise WAreaError("W_AREA_CROSS_SCOPE_BINDING")
    area = areas.get(placement.area_code)
    if area is None or not area.active:
        raise WAreaError("W_AREA_UNKNOWN_OR_INACTIVE")
    if placement.area_revision != area.revision:
        raise WAreaError("W_AREA_STALE_REVISION")
    if placement.channel not in {"pos", "xafchat_qr"}:
        raise WAreaError("W_AREA_CHANNEL_INVALID")
    if placement.table_code:
        if not venue.table_service_enabled:
            raise WAreaError("W_TABLE_SERVICE_DISABLED")
        if placement.table_code not in area.allowed_tables:
            raise WAreaError("W_TABLE_NOT_IN_AREA")
    if placement.channel == "xafchat_qr":
        if not venue.xafchat_qr_enabled or not venue.table_service_enabled:
            raise WAreaError("W_QR_NOT_EFFECTIVE")
        if not placement.table_code:
            raise WAreaError("W_QR_TABLE_REQUIRED")

    # Current SO1 SQL resolves location-specific prices before tenant fallback
    # within THIS SERVER-SELECTED price_code and target. Never fall back
    # to retail when the VIP code has no valid price.
    request = ResolvePrice(
        venue.tenant_id, target_type, target_public_id,
        area.price_code, "XAF", effective_at,
        ScopeType.LOCATION, venue.location_id,
    )
    try:
        price = so1_price_resolver(request)
    except Exception as exc:
        raise WAreaError("W_AREA_SO1_PRICE_UNAVAILABLE") from exc
    if not isinstance(price, Price):
        raise WAreaError("W_AREA_SO1_PRICE_UNAVAILABLE")
    if (price.tenant_id != venue.tenant_id or
            price.target_type != target_type or
            price.target_public_id != target_public_id or
            price.price_code != area.price_code or price.currency != "XAF"):
        raise WAreaError("W_AREA_SO1_WINNER_IDENTITY_MISMATCH")
    if not (price.scope_type is ScopeType.TENANT and price.scope_id is None or
            price.scope_type is ScopeType.LOCATION and price.scope_id == venue.location_id):
        raise WAreaError("W_AREA_SO1_WINNER_SCOPE_MISMATCH")
    if (not price.active or price.effective_from > effective_at or
            price.effective_to is not None and effective_at >= price.effective_to):
        raise WAreaError("W_AREA_SO1_WINNER_NOT_EFFECTIVE")
    try:
        amount = Decimal(price.amount)
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise WAreaError("W_AREA_NON_WHOLE_XAF_PRICE")
    except (ArithmeticError, ValueError, TypeError) as exc:
        if isinstance(exc, WAreaError):
            raise
        raise WAreaError("W_AREA_NON_WHOLE_XAF_PRICE") from exc
    if type(price.row_version) is not int or price.row_version < 1:
        raise WAreaError("W_AREA_PRICE_VERSION_INVALID")

    return RestaurantPriceQuote(
        order_public_id, venue.tenant_id, venue.location_id,
        area.area_code, area.revision, placement.table_code,
        area.price_code, price.public_id, price.row_version,
        target_type, target_public_id, int(amount), "XAF",
        placement.channel, venue.revision,
    )


def assert_quote_current(quote: RestaurantPriceQuote, current: RestaurantPriceQuote) -> None:
    """Order writer must re-check quote identity; never silently reprice open lines."""
    if quote != current:
        raise WAreaError("W_AREA_STALE_OR_CHANGED_QUOTE")
