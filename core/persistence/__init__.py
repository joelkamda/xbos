"""Shared persistence infrastructure for the neutral XBOS kernel.

Consumers import the configuration and metadata submodules explicitly. Keeping this
package initializer side-effect free allows URL resolution to run before SQLAlchemy
metadata or application models are imported.
"""

__all__ = []
