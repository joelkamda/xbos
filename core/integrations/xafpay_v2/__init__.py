"""Canonical XafPay Gateway V2 signed-event consumer boundary."""

from .contract import XafPayV2IntegrationError
from .service import XafPayV2Service

__all__ = ["XafPayV2IntegrationError", "XafPayV2Service"]
