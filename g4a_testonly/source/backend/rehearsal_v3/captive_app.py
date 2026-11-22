"""Explicit synthetic-only G3 captive app (not PC5, not production)."""
from .g3_test_network_guard import install
install()
from .phaseb_app import app
