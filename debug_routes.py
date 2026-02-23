# debug_routes.py

import sys
import os

# Ensure XBOS root is in PYTHONPATH
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY

print("\n=== ROUTE → PERMISSION MAPPINGS ===\n")
for (method, path), perm in PERMISSION_REGISTRY.routes.items():
    print(f"{method}  {path:40} =>  {perm}")

print("\n=== END ===\n")
