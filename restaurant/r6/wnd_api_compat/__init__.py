"""Temporary WND Track-A API compatibility bridge for R6.5 hypercare.

This package is not neutral XBOS authority. It preserves the frozen WND
application contract while the neutral runtime owns process startup and the
neutralized r63 database. It is retired after governed hypercare acceptance.
"""

from .router import router

__all__ = ["router"]
