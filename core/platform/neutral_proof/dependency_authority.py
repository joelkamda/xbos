"""Exact-pin and production-import verification for the PC6 dependency authority."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)$")


def parse_exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError(f"production_dependency_not_exactly_pinned={number}:{line}")
        name, version = match.groups()
        key = name.casefold().replace("_", "-")
        if key in pins:
            raise ValueError(f"duplicate_production_dependency={name}")
        pins[key] = version
    return pins


def production_imports(root: Path) -> dict[str, tuple[str, ...]]:
    """Return third-party top-level imports from application, core, and Alembic runtime code."""
    local = {"core", "scripts"} | {path.stem for path in root.rglob("*.py")}
    standard = set(sys.stdlib_module_names)
    found: dict[str, set[str]] = {}
    candidates = list((root / "core").rglob("*.py"))
    candidates += [root / name for name in ("main.py", "app.py", "startup.py", "database.py", "settings.py")]
    candidates += list((root / "alembic").rglob("*.py")) + list((root / "alembic_neutral").rglob("*.py")) + list((root / "alembic_reconstruction").rglob("*.py"))
    for path in sorted(set(candidates)):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if name not in local and name not in standard and name != "__future__":
                    found.setdefault(name, set()).add(relative)
    return {name: tuple(sorted(paths)) for name, paths in sorted(found.items())}


def verify_dependency_authority(root: Path, contract: dict) -> dict[str, object]:
    pins = parse_exact_pins(root / contract["canonical_manifest"])
    expected = {name.casefold().replace("_", "-"): version for name, version in contract["accepted_pins"].items()}
    if pins != expected:
        raise ValueError(f"production_dependency_pin_set_mismatch={sorted(set(pins)^set(expected))}")
    imports = production_imports(root)
    mapping = contract["module_to_distribution"]
    unmapped = sorted(name for name in imports if name not in mapping)
    if unmapped:
        raise ValueError(f"undeclared_production_imports={unmapped}")
    missing = sorted(distribution for distribution in mapping.values() if distribution.casefold().replace("_", "-") not in pins)
    if missing:
        raise ValueError(f"production_import_has_no_pin={missing}")
    driver_evidence = "\n".join(path.read_text(encoding="utf-8") for path in (root / "database.py", root / "alembic.ini", root / "alembic_neutral.ini", root / "alembic_reconstruction.ini"))
    for driver, distribution in contract["runtime_drivers"].items():
        if driver not in driver_evidence:
            raise ValueError(f"runtime_driver_evidence_missing={driver}")
        if distribution.casefold().replace("_", "-") not in pins:
            raise ValueError(f"runtime_driver_has_no_pin={distribution}")
    residue = {name.casefold().replace("_", "-") for name in contract["excluded_environment_residue"]}
    if residue & set(pins):
        raise ValueError(f"environment_residue_became_authority={sorted(residue & set(pins))}")
    return {"status": "PASS", "pin_count": len(pins), "third_party_imports": sorted(imports), "python": contract["python"]}
