"""XBOS-owned Customer Channel private checkout composition."""
from .contracts import (
    H1BError,
    TrustedCheckoutScope,
    SERVICE_PRINCIPAL,
    CHECKOUT_PERMISSION,
    PRIVATE_ROUTE_PREFIX,
)
from .service import RestaurantCustomerChannelCheckoutAuthority

__all__ = [
    "H1BError",
    "TrustedCheckoutScope",
    "SERVICE_PRINCIPAL",
    "CHECKOUT_PERMISSION",
    "PRIVATE_ROUTE_PREFIX",
    "RestaurantCustomerChannelCheckoutAuthority",
]
