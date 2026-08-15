"""XBOS Platform Administration public authority surface."""
from .contracts import *
from .service import PlatformAdministrationAuthority, PlatformAdministrationError

__all__ = [name for name in globals() if not name.startswith("_")]
