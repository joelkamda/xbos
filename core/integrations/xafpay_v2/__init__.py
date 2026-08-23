"""XafPay Gateway V2 compatibility adapter for isolated XV12 proof."""

from .client import XafPayV2Client
from .contract import XafPayV2IntegrationError
from .service import XafPayV2Service

__all__ = ["XafPayV2Client", "XafPayV2IntegrationError", "XafPayV2Service"]
