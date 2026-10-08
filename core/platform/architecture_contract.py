"""Executable PC0 modular-monolith and authority-boundary contract.

This module is deliberately standard-library only.  Importing or running it does
not import the application, open a database connection, or execute startup code.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from core.platform.release_integrity import canonical_sha256


CONTRACT_DIRECTORY = Path("contracts/platform/v1")
CONTRACT_FILES = {
    "module_map": "pc0_module_map.json",
    "dependency_policy": "pc0_dependency_policy.json",
    "interfaces": "pc0_public_private_interfaces.json",
    "authorities": "pc0_data_authority_register.json",
    "reference_migrations": "pc0_reference_authority_migration_register.json",
    "legacy_exceptions": "pc0_legacy_exception_baseline.json",
    "composition": "pc0_composition_baseline.json",
    "finance": "pc0_frozen_finance_baseline.json",
    "finance_inventory": "pc0_frozen_finance_inventory.json",
    "pc1": "pc1_structural_authority.json",
    "pc2": "pc2_party_authority.json",
    "pc3": "pc3_semantic_authority.json",
    "pc4": "pc4_operating_context_authority.json",
    "pc5": "pc5_identity_policy_audit_authority.json",
    "kernel": "pc0_kernel_boundaries.json",
}
ROOT_PYTHON_MODULES = {
    "app", "container", "database", "logging_config", "main", "settings", "startup"
}
H1B_SUCCESSOR_FILE = "pc0_h1b_composition_successor.json"
_H1B_SCHEMA = "xbos.platform.pc0-h1b-composition-successor.v1"
_H1B_AUTHORITY = "XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION"
_H1B_CLASS = "POSTHOC_PC0_COMPOSITION_AND_NON_FINANCE_EXTENSION_SUCCESSOR_ONLY"
_H1B_SOURCE_BASE = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
_H1B_STARTUP_HISTORICAL = "465fb8e613f66de8f77b7a3d4b4566c42dda1ad5db9435608a66cfa2fb20e698"
_H1B_STARTUP_SUCCESSOR = "fde45446f8f85df518e1997a5b5005308f6314ed4088a582a7fefeb6eee90dce"
_H1B_EXTENSION_HASHES = {
    "sql/cch_customer_channel_checkout_authority_up.sql": "a8e9663911a11c1b3df9dea462ceb20ca6598329baf1144af2f9f50fa937a3fb",
    "sql/cch_customer_channel_checkout_authority_down.sql": "4344980ab4d8821076185a1987c6cb0df744d3ccc782138923a844708af10c01",
    "versions/cch_customer_channel_checkout_authority_047.py": "8f9b6ca94353c6fe83843a37ae1e4be619442debfdf55a12f460a16dc57d6859",
}
_H1B_PC0_RELEASE_HISTORICAL = {
    "core/platform/architecture_contract.py": "eae3265ad7632fcb9bc811ccda290579d59583ebc15aaf8d762a7262c93755b8",
    "tests/contracts/test_pc0_kernel_boundaries.py": "ece19ea243bc1725ebf0e7446af69c28ff83411cd2ff0f2cf717a9de842d06f9",
}

_NCE_AUTHORITY = "XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION"
_NCE_COMMIT = "92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611"
_NCE_TAG = "xbos-nce-r1-r1-e2-r1-xafpay-v2-event-consumer-accepted-20260923"
_NCE_COMMON_PARENT = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
_NCE_KERNEL_ROUTER_HISTORICAL = "e3bd3ee9be4006337ecb07eb53f61fb01838c2d952f915c3361481d0fd109d7f"
_NCE_KERNEL_ROUTER_SUCCESSOR = "a8b4a8b645ed7dd31367eb4dfa5643118ae7e518370817fdd5ddba997dd21c3d"
_NCE_SOURCE_ROOT = "core/integrations/xafpay_v2"
_NCE_SOURCE_HASHES = {
    "core/integrations/xafpay_v2/__init__.py": "81a784b6db2386847bab5b0a86633d85ae57986e76c003dd11e46dd5dd7fc38a",
    "core/integrations/xafpay_v2/contract.py": "8bb5e87bbd49d94b0a45499ca544c0f21964e84f867d3c9389c24afe8b54fb5f",
    "core/integrations/xafpay_v2/repository.py": "da0065acac20914b5f90063b9f72315aba41f06d15639ebd1b4e0cdbccaea8a8",
    "core/integrations/xafpay_v2/router.py": "21801c3bec26128b19426edab6066448fd98f72bc4ac56b7d477f27441b10e84",
    "core/integrations/xafpay_v2/service.py": "5af5e6484fd03bbfe843c1d21c3c01094d3166ff179ba3f8bbcf77f3f006cc51",
}
_NCE_AUTHORIZED_EDGES = {
    ("core/api/kernel_router.py", "core.integrations.xafpay_v2.router", "composition", "xafpay"),
    ("core/integrations/xafpay_v2/router.py", "database", "xafpay", "application"),
}


class PC0ArchitectureError(AssertionError):
    """A deterministic PC0 contract violation."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ImportEdge:
    source_path: str
    import_name: str
    source_module: str
    target_module: str

    def key(self) -> tuple[str, str, str, str]:
        return (self.source_path, self.import_name, self.source_module, self.target_module)


def _fail(code: str, detail: str) -> None:
    raise PC0ArchitectureError(code, detail)


def _load_json(root: Path, name: str) -> dict[str, Any]:
    path = root / CONTRACT_DIRECTORY / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-CONTRACT-READ", f"{path.as_posix()}: {exc}")


def _sha256_file(path: Path) -> str:
    return canonical_sha256(path)


def _source_sha256(path: Path) -> str:
    """Hash the canonical Git text, independent of checkout newline policy."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _validate_h1b_successor_contract(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema", "authority", "successor_class", "source_base",
        "historical_pc0_composition_baseline_mutated",
        "historical_pc0_finance_inventory_mutated",
        "historical_pc0_release_manifest_mutated",
        "composition_override", "non_finance_extensions", "migration",
        "pc0_release_replacements", "allowed_paths", "nce_additive_successor",
    }
    if set(contract) != expected_keys:
        _fail("PC0-H1B-SUCCESSOR-SHAPE", f"keys={sorted(contract)}")
    if contract.get("schema") != _H1B_SCHEMA:
        _fail("PC0-H1B-SUCCESSOR-SCHEMA", str(contract.get("schema")))
    if contract.get("authority") != _H1B_AUTHORITY or contract.get("successor_class") != _H1B_CLASS:
        _fail("PC0-H1B-SUCCESSOR-AUTHORITY", "authority or successor class mismatch")
    if contract.get("source_base") != _H1B_SOURCE_BASE:
        _fail("PC0-H1B-SUCCESSOR-BASE", str(contract.get("source_base")))
    for key in (
        "historical_pc0_composition_baseline_mutated",
        "historical_pc0_finance_inventory_mutated",
        "historical_pc0_release_manifest_mutated",
    ):
        if contract.get(key) is not False:
            _fail("PC0-H1B-HISTORICAL-REWRITE", key)

    nce = contract.get("nce_additive_successor")
    expected_nce_keys = {
        "authority", "nce_commit", "nce_tag", "common_parent",
        "kernel_router_override", "module_overlay", "authorized_dependency_edges",
    }
    if not isinstance(nce, dict) or set(nce) != expected_nce_keys:
        _fail("PC0-NCE-SUCCESSOR-SHAPE", str(nce))
    if (
        nce.get("authority") != _NCE_AUTHORITY
        or nce.get("nce_commit") != _NCE_COMMIT
        or nce.get("nce_tag") != _NCE_TAG
        or nce.get("common_parent") != _NCE_COMMON_PARENT
    ):
        _fail("PC0-NCE-SUCCESSOR-AUTHORITY", "accepted NCE identity mismatch")
    kernel = nce.get("kernel_router_override")
    if not isinstance(kernel, dict) or set(kernel) != {
        "path", "historical_sha256", "successor_sha256", "required_markers"
    }:
        _fail("PC0-NCE-KERNEL-OVERRIDE", "invalid shape")
    if (
        kernel.get("path") != "core/api/kernel_router.py"
        or kernel.get("historical_sha256") != _NCE_KERNEL_ROUTER_HISTORICAL
        or kernel.get("successor_sha256") != _NCE_KERNEL_ROUTER_SUCCESSOR
        or kernel.get("required_markers") != [
            "from core.integrations.xafpay_v2.router import router as xafpay_v2_router",
            'prefix="/integrations/xafpay-v2"',
        ]
    ):
        _fail("PC0-NCE-KERNEL-OVERRIDE", str(kernel))
    if _source_sha256(root / "core/api/kernel_router.py") != _NCE_KERNEL_ROUTER_SUCCESSOR:
        _fail("PC0-NCE-KERNEL-CHANGED", "core/api/kernel_router.py")
    kernel_source = (root / "core/api/kernel_router.py").read_text(encoding="utf-8")
    for marker in kernel["required_markers"]:
        if marker not in kernel_source:
            _fail("PC0-NCE-KERNEL-MARKER", marker)
    overlay = nce.get("module_overlay")
    if not isinstance(overlay, dict) or set(overlay) != {"module_code", "source_root", "files"}:
        _fail("PC0-NCE-MODULE-OVERLAY", "invalid shape")
    if overlay.get("module_code") != "xafpay" or overlay.get("source_root") != _NCE_SOURCE_ROOT:
        _fail("PC0-NCE-MODULE-OVERLAY", str(overlay))
    files = overlay.get("files")
    if not isinstance(files, list):
        _fail("PC0-NCE-MODULE-OVERLAY", "files missing")
    by_path = {item.get("path"): item for item in files if isinstance(item, dict)}
    if len(by_path) != len(files) or set(by_path) != set(_NCE_SOURCE_HASHES):
        _fail("PC0-NCE-SOURCE-FILES", str(sorted(by_path)))
    for relative, expected_hash in _NCE_SOURCE_HASHES.items():
        item = by_path[relative]
        if set(item) != {"path", "sha256"} or item.get("sha256") != expected_hash:
            _fail("PC0-NCE-SOURCE-FILES", relative)
        if _source_sha256(root / relative) != expected_hash:
            _fail("PC0-NCE-SOURCE-CHANGED", relative)
    edges = nce.get("authorized_dependency_edges")
    if not isinstance(edges, list):
        _fail("PC0-NCE-DEPENDENCY-EDGES", "missing")
    edge_set = {
        (
            item.get("source_path"), item.get("import_name"),
            item.get("source_module"), item.get("target_module"),
        )
        for item in edges if isinstance(item, dict)
    }
    if len(edge_set) != len(edges) or edge_set != _NCE_AUTHORIZED_EDGES:
        _fail("PC0-NCE-DEPENDENCY-EDGES", str(sorted(edge_set)))

    composition = contract.get("composition_override")
    if not isinstance(composition, dict) or set(composition) != {
        "path", "historical_sha256", "successor_sha256", "required_markers"
    }:
        _fail("PC0-H1B-COMPOSITION-OVERRIDE", "invalid shape")
    if composition.get("path") != "startup.py":
        _fail("PC0-H1B-COMPOSITION-OVERRIDE", str(composition.get("path")))
    if composition.get("historical_sha256") != _H1B_STARTUP_HISTORICAL:
        _fail("PC0-H1B-COMPOSITION-HISTORICAL", str(composition.get("historical_sha256")))
    if composition.get("successor_sha256") != _H1B_STARTUP_SUCCESSOR:
        _fail("PC0-H1B-COMPOSITION-SUCCESSOR", str(composition.get("successor_sha256")))
    markers = composition.get("required_markers")
    expected_markers = [
        "from restaurant.customer_channel.router import router as customer_channel_router",
        "app.include_router(customer_channel_router)",
    ]
    if markers != expected_markers:
        _fail("PC0-H1B-COMPOSITION-MARKERS", str(markers))
    startup = root / "startup.py"
    if _source_sha256(startup) != _H1B_STARTUP_SUCCESSOR:
        _fail("PC0-H1B-COMPOSITION-CHANGED", "startup.py")
    source = startup.read_text(encoding="utf-8")
    for marker in expected_markers:
        if marker not in source:
            _fail("PC0-H1B-COMPOSITION-MARKER", marker)

    extensions = contract.get("non_finance_extensions")
    if not isinstance(extensions, list) or len(extensions) != 3:
        _fail("PC0-H1B-EXTENSIONS", "exactly three extensions required")
    by_path: dict[str, dict[str, Any]] = {}
    for item in extensions:
        if not isinstance(item, dict) or set(item) != {"owner", "root", "path", "sha256", "reason"}:
            _fail("PC0-H1B-EXTENSIONS", str(item))
        path = item.get("path")
        if path in by_path:
            _fail("PC0-H1B-EXTENSIONS", f"duplicate={path}")
        by_path[path] = item
    if set(by_path) != set(_H1B_EXTENSION_HASHES):
        _fail("PC0-H1B-EXTENSIONS", f"paths={sorted(by_path)}")
    for relative, expected_hash in _H1B_EXTENSION_HASHES.items():
        item = by_path[relative]
        if (
            item.get("owner") != "H1B_CUSTOMER_CHANNEL"
            or item.get("root") != "alembic_neutral"
            or item.get("sha256") != expected_hash
            or item.get("reason") != "H1B_CUSTOMER_CHANNEL_NON_FINANCE_SCHEMA_EXTENSION"
        ):
            _fail("PC0-H1B-EXTENSIONS", relative)
        if _source_sha256(root / "alembic_neutral" / relative) != expected_hash:
            _fail("PC0-NON-FINANCE-EXTENSION-CHANGED", f"alembic_neutral/{relative}")

    migration = contract.get("migration")
    if migration != {
        "revision": "cch_customer_channel_checkout_authority_047",
        "parent": "r1_restaurant_order_line_lifecycle_046",
        "new_table_count": 2,
        "financial_effect": "ZERO",
    }:
        _fail("PC0-H1B-MIGRATION-SUCCESSOR", str(migration))

    replacements = contract.get("pc0_release_replacements")
    if not isinstance(replacements, list) or len(replacements) != 2:
        _fail("PC0-H1B-RELEASE-REPLACEMENTS", "exactly two replacements required")
    replacement_by_path = {item.get("path"): item for item in replacements if isinstance(item, dict)}
    if set(replacement_by_path) != set(_H1B_PC0_RELEASE_HISTORICAL):
        _fail("PC0-H1B-RELEASE-REPLACEMENTS", f"paths={sorted(replacement_by_path)}")
    for relative, historical in _H1B_PC0_RELEASE_HISTORICAL.items():
        item = replacement_by_path[relative]
        if set(item) != {"path", "historical_sha256", "successor_sha256"}:
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", relative)
        actual = _source_sha256(root / relative)
        if item.get("historical_sha256") != historical or item.get("successor_sha256") != actual:
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", relative)

    allowed = contract.get("allowed_paths")
    expected_allowed = sorted({
        "startup.py",
        "core/api/kernel_router.py",
        *_NCE_SOURCE_HASHES,
        *(f"alembic_neutral/{path}" for path in _H1B_EXTENSION_HASHES),
        *_H1B_PC0_RELEASE_HISTORICAL,
    })
    if allowed != expected_allowed:
        _fail("PC0-H1B-ALLOWED-PATHS", str(allowed))
    return contract


def _load_h1b_successor(root: Path) -> dict[str, Any] | None:
    path = root / CONTRACT_DIRECTORY / H1B_SUCCESSOR_FILE
    if not path.is_file():
        return None
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-H1B-SUCCESSOR-READ", str(exc))
    return _validate_h1b_successor_contract(root, contract)


def _pc8_composition_replacements(root: Path) -> dict[str, tuple[str, str]]:
    contract_path = root / CONTRACT_DIRECTORY / "pc8_h1b_private_route_admission_successor.json"
    manifest_path = root / CONTRACT_DIRECTORY / "pc8_release_manifest.json"
    if not contract_path.is_file() and not manifest_path.is_file():
        return {}
    if not contract_path.is_file() or not manifest_path.is_file():
        _fail("PC0-PC8-SUCCESSOR-INCOMPLETE", "contract/manifest pair required")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-PC8-SUCCESSOR-READ", str(exc))
    if (
        contract.get("schema") != "xbos.platform.pc8-h1b-private-route-admission-successor.v1"
        or contract.get("source_base") != _H1B_SOURCE_BASE
        or contract.get("private_prefix") != "/internal/customer-channel/v1"
        or contract.get("new_platform_business_authority") is not False
        or contract.get("new_platform_schema_authority") is not False
    ):
        _fail("PC0-PC8-SUCCESSOR-AUTHORITY", "private-route successor mismatch")
    expected = {
        "core/middleware/auth_middleware.py": "4a8cafe8e87069499da4ee798ba060e54b757224930e131a434f8b99f18e2366",
        "core/middleware/tenant_middleware.py": "5151239379e4b6e686bc168818d655c94e2945df324ee5452441549deb83dd9d",
        "core/middleware/branch_middleware.py": "af0c6cc09242d60f54c7d300e5fadda872b13db2e793307afedf47036bd5554f",
    }
    bases = contract.get("accepted_base_canonical_sha256", {})
    artifacts = {item.get("path"): item.get("sha256") for item in manifest.get("artifacts", [])}
    replacements: dict[str, tuple[str, str]] = {}
    for relative, historical in expected.items():
        actual = _source_sha256(root / relative)
        if bases.get(relative) != historical or artifacts.get(relative) != actual:
            _fail("PC0-PC8-SUCCESSOR-INTEGRITY", relative)
        replacements[relative] = (historical, actual)
    return replacements


_TRANSIENT_CACHE_COMPONENTS = {".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}


def _is_transient_runtime_artifact(relative: Path) -> bool:
    if relative.suffix.lower() in {".pyc", ".pyo"}:
        return True
    return any(part in _TRANSIENT_CACHE_COMPONENTS for part in relative.parts)


def _tree_fingerprint(root: Path, relative_root: str, inventory: Iterable[str], extensions: dict[str, str] | None = None) -> tuple[int, str]:
    base = root / relative_root
    expected = list(inventory)
    if len(expected) != len(set(expected)) or expected != sorted(expected):
        _fail("PC0-FROZEN-FINANCE-INVENTORY", f"{relative_root}: inventory must be unique and sorted")
    actual = sorted(
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and not _is_transient_runtime_artifact(path.relative_to(base))
    )
    extensions = extensions or {}
    allowed = set(expected) | set(extensions)
    if set(actual) != allowed:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - allowed)
        _fail(
            "PC0-FROZEN-FINANCE-INVENTORY",
            f"{relative_root}: missing={missing}, unexpected={unexpected}",
        )
    for relative, expected_hash in extensions.items():
        actual_hash = _source_sha256(base / relative)
        if actual_hash != expected_hash:
            _fail("PC0-NON-FINANCE-EXTENSION-CHANGED", f"{relative_root}/{relative}")
    files = [base / relative for relative in expected]
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return len(files), digest.hexdigest()


def _module_roots(module_map: dict[str, Any]) -> list[tuple[str, str]]:
    roots = [
        (source_root.rstrip("/"), module["code"])
        for module in module_map["modules"]
        for source_root in module["source_roots"]
    ]
    return sorted(roots, key=lambda pair: len(pair[0]), reverse=True)


def _module_for_path(path: str, roots: Iterable[tuple[str, str]]) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./")
    for source_root, module in roots:
        if normalized == source_root or normalized.startswith(source_root + "/"):
            return module
    return None


def validate_frozen_module_descendants(
    frozen_modules: dict[str, tuple[str, str]],
    module_map: dict[str, Any],
    authorities: dict[str, Any],
    reference_migrations: dict[str, Any],
) -> None:
    """Protect frozen capabilities while allowing exactly registered promotions."""
    modules = module_map.get("modules", [])
    codes = [item.get("code") for item in modules]
    if None in codes or len(codes) != len(set(codes)):
        _fail("PC0-MODULE-MAP", "duplicate/conflicting module ownership")
    actual = {item["code"]: (item.get("owner"), item.get("kind")) for item in modules}
    missing = sorted(set(frozen_modules) - set(actual))
    if missing:
        _fail("PC0-FROZEN-MODULE-MISSING", str(missing))

    governed = [item for item in reference_migrations.get("entries", []) if item.get("module_code")]
    by_module = {item["module_code"]: item for item in governed}
    if len(by_module) != len(governed):
        _fail("PC0-MODULE-PROMOTION", "duplicate governed module migration")
    authority_rows = [item for item in authorities.get("authorities", []) if item.get("module")]
    authority_by_module = {item["module"]: item for item in authority_rows}
    if len(authority_by_module) != len(authority_rows):
        _fail("PC0-MODULE-PROMOTION", "duplicate module data authority")

    required = (
        "current_authority", "target_authority", "compatibility_path",
        "retirement_owner", "retirement_milestone", "previous_module_owner",
        "previous_module_kind", "target_module_owner", "target_module_kind",
        "target_data_authority",
    )
    for code, frozen_identity in frozen_modules.items():
        current_identity = actual[code]
        if current_identity == frozen_identity:
            continue
        migration = by_module.get(code)
        authority = authority_by_module.get(code)
        if not migration or not authority or not all(isinstance(migration.get(key), str) and migration[key] for key in required):
            _fail("PC0-MODULE-PROMOTION", f"unregistered promotion={code}")
        previous = (migration["previous_module_owner"], migration["previous_module_kind"])
        target = (migration["target_module_owner"], migration["target_module_kind"])
        if previous != frozen_identity or target != current_identity:
            _fail("PC0-MODULE-PROMOTION", f"authority transition mismatch={code}")
        if authority.get("code") != migration["target_data_authority"] or authority.get("owner") != current_identity[0]:
            _fail("PC0-MODULE-PROMOTION", f"target data authority mismatch={code}")


def _path_for_import(root: Path, source_path: str, import_name: str, level: int = 0) -> str | None:
    if level:
        source_parts = Path(source_path).with_suffix("").parts[:-1]
        keep = max(0, len(source_parts) - level + 1)
        import_parts = tuple(part for part in import_name.split(".") if part)
        parts = source_parts[:keep] + import_parts
    else:
        parts = tuple(part for part in import_name.split(".") if part)
    if not parts:
        return None
    candidates = [Path(*parts).with_suffix(".py"), Path(*parts) / "__init__.py"]
    if level == 0 and parts[0] not in {"core", *ROOT_PYTHON_MODULES}:
        local = Path(source_path).parent.joinpath(*parts)
        candidates.extend([local.with_suffix(".py"), local / "__init__.py"])
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def _imports(source: str, source_path: str) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:
        _fail("PC0-PYTHON-SYNTAX", f"{source_path}:{exc.lineno}: {exc.msg}")
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                found.append((base, node.level))
            else:
                found.extend((alias.name, node.level) for alias in node.names if alias.name != "*")
    return found


def _edges_for_source(
    root: Path,
    source_path: str,
    source: str,
    roots: list[tuple[str, str]],
    admitted_unmapped_targets: set[tuple[str, str, str]] | None = None,
) -> list[ImportEdge]:
    source_module = _module_for_path(source_path, roots)
    if source_module is None:
        _fail("PC0-UNMAPPED-SOURCE", source_path)
    edges: list[ImportEdge] = []
    for import_name, level in _imports(source, source_path):
        target_path = _path_for_import(root, source_path, import_name, level)
        if target_path is None:
            continue
        target_module = _module_for_path(target_path, roots)
        if target_module is None:
            key = (source_path, import_name, target_path)
            if admitted_unmapped_targets and key in admitted_unmapped_targets:
                continue
            _fail("PC0-UNMAPPED-TARGET", f"{source_path} -> {import_name} ({target_path})")
        if source_module != target_module:
            edges.append(ImportEdge(source_path, import_name, source_module, target_module))
    return edges


def _exception_keys(exceptions: dict[str, Any]) -> dict[tuple[str, str, str, str], str]:
    if exceptions.get("matching") != "exact" or exceptions.get("wildcards_allowed") is not False:
        _fail("PC0-EXCEPTION-MODE", "only exact matching with wildcards disabled is permitted")
    result: dict[tuple[str, str, str, str], str] = {}
    ids: set[str] = set()
    required = ("source_path", "import_name", "source_module", "target_module")
    for item in exceptions.get("exceptions", []):
        exception_id = item.get("id")
        if not exception_id or exception_id in ids:
            _fail("PC0-EXCEPTION-ID", f"duplicate or blank id: {exception_id!r}")
        ids.add(exception_id)
        if any(char in str(item.get(field, "")) for field in required for char in "*?["):
            _fail("PC0-EXCEPTION-WILDCARD", exception_id)
        for field in (*required, "rationale", "retirement_owner", "retirement_milestone"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                _fail("PC0-EXCEPTION-INCOMPLETE", f"{exception_id}.{field}")
        key = tuple(item[field] for field in required)
        if key in result:
            _fail("PC0-EXCEPTION-DUPLICATE", f"{result[key]} and {exception_id}")
        result[key] = exception_id
    return result


def _evaluate_edges(
    edges: Iterable[ImportEdge], policy: dict[str, Any], exception_keys: dict[tuple[str, str, str, str], str]
) -> tuple[list[ImportEdge], set[str]]:
    allowed = policy["allowed_directions"]
    violations: list[ImportEdge] = []
    used: set[str] = set()
    for edge in edges:
        if edge.target_module in allowed.get(edge.source_module, []):
            continue
        exception_id = exception_keys.get(edge.key())
        if exception_id:
            used.add(exception_id)
        else:
            violations.append(edge)
    return violations, used


def evaluate_source_text(root: str | Path, source_path: str, source: str) -> list[dict[str, str]]:
    """Return unapproved cross-module edges for a proposed source file."""
    root_path = Path(root).resolve()
    module_map = _load_json(root_path, CONTRACT_FILES["module_map"])
    policy = _load_json(root_path, CONTRACT_FILES["dependency_policy"])
    exceptions = _load_json(root_path, CONTRACT_FILES["legacy_exceptions"])
    roots = _module_roots(module_map)
    edges = _edges_for_source(root_path, source_path, source, roots)
    violations, _ = _evaluate_edges(edges, policy, _exception_keys(exceptions))
    return [edge.__dict__ for edge in violations]


def _production_python_files(root: Path, module_map: dict[str, Any]) -> list[Path]:
    # Scan the entire production namespace, not just known roots, so a newly
    # introduced directory cannot evade the module map.
    files: set[Path] = set((root / "core").rglob("*.py"))
    for module in module_map["modules"]:
        for source_root in module["source_roots"]:
            path = root / source_root
            if path.is_file() and path.suffix == ".py":
                files.add(path)
            elif path.is_dir():
                files.update(candidate for candidate in path.rglob("*.py") if candidate.is_file())
    return sorted(files)


def _validate_modules(module_map: dict[str, Any], policy: dict[str, Any], interfaces: dict[str, Any]) -> None:
    modules = [item["code"] for item in module_map.get("modules", [])]
    if len(modules) != len(set(modules)) or not modules:
        _fail("PC0-MODULE-MAP", "module codes must be unique and nonempty")
    if set(policy.get("allowed_directions", {})) != set(modules):
        _fail("PC0-POLICY-COVERAGE", "dependency policy must declare every module exactly once")
    for source, targets in policy["allowed_directions"].items():
        if len(targets) != len(set(targets)) or not set(targets).issubset(modules):
            _fail("PC0-POLICY-TARGET", source)
    declared = [item.get("module") for item in interfaces.get("interfaces", [])]
    if len(declared) != len(set(declared)) or set(declared) != set(modules):
        _fail("PC0-INTERFACE-COVERAGE", "interface declarations must match module map")
    for item in interfaces["interfaces"]:
        public, private = item.get("public"), item.get("private")
        if not isinstance(public, list) or not isinstance(private, list):
            _fail("PC0-INTERFACE-SHAPE", item["module"])
        if set(public) & set(private):
            _fail("PC0-INTERFACE-OVERLAP", item["module"])
        if len(public) != len(set(public)) or len(private) != len(set(private)):
            _fail("PC0-INTERFACE-DUPLICATE", item["module"])


def _validate_authorities(authorities: dict[str, Any]) -> None:
    items = authorities.get("authorities", [])
    codes = [item.get("code") for item in items]
    if not items or len(codes) != len(set(codes)):
        _fail("PC0-AUTHORITY-UNIQUE", "every authority code must be unique")
    for item in items:
        owner = item.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            _fail("PC0-AUTHORITY-OWNER", str(item.get("code")))
    required = authorities.get("required_authorities", codes)
    if len(required) != len(set(required)) or set(required) != set(codes):
        _fail("PC0-AUTHORITY-COVERAGE", "required authority list does not match register")


def _validate_reference_migrations(register: dict[str, Any]) -> None:
    entries = register.get("entries", [])
    references = [entry.get("reference") for entry in entries]
    if len(references) != len(set(references)) or set(references) != set(register.get("required_references", [])):
        _fail("PC0-REFERENCE-COVERAGE", "required references must appear exactly once")
    fields = ("current_authority", "target_authority", "compatibility_path", "retirement_owner", "retirement_milestone")
    for entry in entries:
        for field in fields:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                _fail("PC0-REFERENCE-INCOMPLETE", f"{entry.get('reference')}.{field}")


def _validate_composition(
    root: Path, composition: dict[str, Any], successor: dict[str, Any] | None = None
) -> None:
    if successor is None:
        successor = _load_h1b_successor(root)
    else:
        successor = _validate_h1b_successor_contract(root, successor)
    if composition.get("fingerprint_mode") != "sha256_git_canonical_lf":
        _fail("PC0-COMPOSITION-FINGERPRINT-MODE", str(composition.get("fingerprint_mode")))
    override = successor.get("composition_override") if successor else None
    nce_override = (
        successor.get("nce_additive_successor", {}).get("kernel_router_override")
        if successor else None
    )
    pc8_replacements = _pc8_composition_replacements(root)
    for relative, expected in composition.get("files", {}).items():
        actual = _source_sha256(root / relative)
        if actual == expected:
            continue
        if (
            override
            and relative == override["path"]
            and expected == override["historical_sha256"]
            and actual == override["successor_sha256"]
        ):
            continue
        if (
            nce_override
            and relative == nce_override["path"]
            and expected == nce_override["historical_sha256"]
            and actual == nce_override["successor_sha256"]
        ):
            continue
        pc8 = pc8_replacements.get(relative)
        if pc8 and pc8 == (expected, actual):
            continue
        _fail("PC0-COMPOSITION-CHANGED", f"{relative}: {actual} != {expected}")
    for relative, markers in composition.get("markers", {}).items():
        source = (root / relative).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                _fail("PC0-COMPOSITION-MARKER", f"{relative}: {marker}")
    facts = composition.get("facts", {})
    if facts.get("canonical_entrypoint") != "main:app" or facts.get("compatibility_entrypoint") != "app:app":
        _fail("PC0-ENTRYPOINT", "canonical or compatibility entrypoint changed")
    if facts.get("production_dependency_authority") != "requirements-prod.txt":
        _fail("PC0-DEPENDENCY-AUTHORITY", "requirements-prod.txt must remain canonical")


def _migration_revisions(root: Path) -> tuple[list[str], list[str]]:
    revisions: dict[str, str | None] = {}
    for path in sorted((root / "alembic_neutral/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        if "revision" in values:
            if values["revision"] in revisions:
                _fail("PC0-MIGRATION-LINEAGE", f"duplicate revision {values['revision']}")
            revisions[values["revision"]] = values.get("down_revision")
    parents = {parent for parent in revisions.values() if isinstance(parent, str)}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        return heads, []
    lineage: list[str] = []
    current: str | None = heads[0]
    while current:
        if current in lineage or current not in revisions:
            _fail("PC0-MIGRATION-LINEAGE", f"broken or cyclic lineage at {current}")
        lineage.append(current)
        current = revisions[current]
    return heads, list(reversed(lineage))


def _validate_migration_lineage(
    heads: list[str], lineage: list[str], finance: dict[str, Any], accepted_heads: Iterable[str] = ()
) -> None:
    """Protect the immutable Finance prefix while permitting one linear descendant tail."""
    if isinstance(accepted_heads, str):
        accepted_heads = (accepted_heads,)
    frozen = finance.get("lineage", [])
    canonical = finance.get("canonical_head")
    if not frozen or frozen[-1] != canonical:
        _fail("PC0-MIGRATION-LINEAGE", "frozen Finance lineage or canonical head declaration is invalid")
    if len(heads) != 1:
        _fail("PC0-MIGRATION-HEAD", f"heads={heads}, lineage={lineage}")
    if len(lineage) < len(frozen) or lineage[:len(frozen)] != frozen:
        _fail("PC0-MIGRATION-HEAD", f"frozen_prefix={frozen}, heads={heads}, lineage={lineage}")
    declared = [head for head in accepted_heads if head]
    declared_end = len(frozen) + len(declared)
    if len(lineage) < declared_end or lineage[len(frozen):declared_end] != declared:
        _fail("PC0-MIGRATION-HEAD", f"declared_descendants={declared}, heads={heads}, lineage={lineage}")
    if heads != [lineage[-1]]:
        _fail("PC0-MIGRATION-HEAD", f"heads={heads}, lineage={lineage}")


def _validate_finance(
    root: Path,
    finance: dict[str, Any],
    inventory: dict[str, Any],
    accepted_heads: Iterable[str] = (),
    successor: dict[str, Any] | None = None,
) -> None:
    if successor is None:
        successor = _load_h1b_successor(root)
    else:
        successor = _validate_h1b_successor_contract(root, successor)
    if isinstance(accepted_heads, str):
        accepted_heads = (accepted_heads,)
    if finance.get("fingerprint_mode") != "sha256_git_canonical_lf":
        _fail("PC0-FINANCE-FINGERPRINT-MODE", str(finance.get("fingerprint_mode")))
    if inventory.get("freeze_commit") != finance.get("freeze_commit"):
        _fail("PC0-FROZEN-FINANCE-INVENTORY", "inventory checkpoint does not match baseline")
    inventory_trees = {tree.get("root"): tree for tree in inventory.get("trees", [])}
    if set(inventory_trees) != {tree.get("root") for tree in finance.get("trees", [])}:
        _fail("PC0-FROZEN-FINANCE-INVENTORY", "protected tree coverage does not match baseline")
    extensions_by_root: dict[str, dict[str, str]] = {}
    for item in inventory.get("authorized_non_finance_extensions", []):
        owner = item.get("owner")
        valid_owner = isinstance(owner, str) and (
            (owner.startswith("PC") and owner[2:].isdigit() and int(owner[2:]) >= 1)
            or (owner.startswith("SO") and owner[2:].isdigit() and 1 <= int(owner[2:]) <= 10)
            or (owner.startswith("PK") and (owner == "PK" or owner[2:].isdigit()))
            or owner == "PA"
        )
        if not valid_owner or not all(isinstance(item.get(key), str) and item[key] for key in ("root","path","sha256")):
            _fail("PC0-NON-FINANCE-EXTENSION", str(item))
        extensions_by_root.setdefault(item["root"], {})[item["path"]] = item["sha256"]
    if successor:
        for item in successor["non_finance_extensions"]:
            extensions_by_root.setdefault(item["root"], {})[item["path"]] = item["sha256"]
    for tree in finance.get("trees", []):
        declared = inventory_trees[tree["root"]]
        files = declared.get("files", [])
        suffixes = set(declared.get("protected_suffixes", []))
        if not suffixes or any(Path(relative).suffix not in suffixes for relative in files):
            _fail("PC0-FROZEN-FINANCE-INVENTORY", f"{tree['root']}: invalid protected suffix declaration")
        count, actual = _tree_fingerprint(root, tree["root"], files, extensions_by_root.get(tree["root"]))
        if count != tree["file_count"] or actual != tree["sha256"]:
            _fail("PC0-FROZEN-FINANCE-CHANGED", f"{tree['root']}: count={count}, sha256={actual}")
    heads, lineage = _migration_revisions(root)
    _validate_migration_lineage(heads, lineage, finance, accepted_heads)
    if successor:
        migration = successor["migration"]
        if heads != [migration["revision"]] or lineage[-2:] != [migration["parent"], migration["revision"]]:
            _fail("PC0-H1B-MIGRATION-SUCCESSOR", f"heads={heads}, tail={lineage[-2:]}")
    boundaries = finance.get("boundaries", {})
    if boundaries.get("migration") != "NONE" or boundaries.get("schema_neutral") is not True:
        _fail("PC0-SCHEMA-NEUTRAL", "PC0 may not carry a migration")


def _validate_kernel(kernel: dict[str, Any]) -> None:
    if kernel.get("scope") != [f"PC0.{number}" for number in range(1, 9)]:
        _fail("PC0-SCOPE", "PC0.1-PC0.8 must be complete")
    if kernel.get("platform_core_wbs_obligations") != 80:
        _fail("PC0-WBS", "the authoritative Platform Core obligation count is 80")
    exclusions = set(kernel.get("exclusions", []))
    required = {"alembic_migration", "database_write", "runtime_behavior_change", "pc1_pc6_implementation"}
    if not required.issubset(exclusions):
        _fail("PC0-EXCLUSIONS", f"missing {sorted(required - exclusions)}")


def validate_pc0(root: str | Path, validate_release: bool = True) -> dict[str, Any]:
    """Validate the complete static PC0 contract and return deterministic counts."""
    root_path = Path(root).resolve()
    contracts = {key: _load_json(root_path, name) for key, name in CONTRACT_FILES.items()}
    successor = _load_h1b_successor(root_path)
    _validate_modules(contracts["module_map"], contracts["dependency_policy"], contracts["interfaces"])
    if set(contracts["composition"].get("files", {})) != set(contracts["module_map"].get("composition_files", [])):
        _fail("PC0-COMPOSITION-COVERAGE", "composition baseline must exactly match the module-map inventory")
    _validate_authorities(contracts["authorities"])
    _validate_reference_migrations(contracts["reference_migrations"])
    _validate_composition(root_path, contracts["composition"], successor)
    descendant_heads = [
        contracts["pc1"].get("accepted_head"), contracts["pc2"].get("accepted_head"),
        contracts["pc3"].get("accepted_head"), contracts["pc4"].get("accepted_head"),
        contracts["pc5"].get("accepted_head"),
    ]
    # Shared Operations descendants are a bounded constitutional sequence SO1-SO10.
    # Discover them prospectively so each legitimate next milestone does not require
    # another hard-coded architecture validator edit merely to extend the lineage.
    for number in range(1, 11):
        contract = root_path / f"contracts/shared_operations/v1/so{number}_authority.json"
        if contract.is_file():
            descendant_heads.append(json.loads(contract.read_text(encoding="utf-8")).get("accepted_head"))
    aggregate_contract = root_path / "contracts/shared_operations/v1/so_aggregate_conformance_freeze.json"
    if aggregate_contract.is_file():
        descendant_heads.append(json.loads(aggregate_contract.read_text(encoding="utf-8")).get("accepted_head"))
    # Pack Platform descendants are likewise prospective governed descendants.
    for contract in sorted((root_path / "contracts/packs/v1").glob("pk*_authority.json")) if (root_path / "contracts/packs/v1").is_dir() else []:
        descendant_heads.append(json.loads(contract.read_text(encoding="utf-8")).get("accepted_head"))
    _validate_finance(
        root_path,
        contracts["finance"],
        contracts["finance_inventory"],
        descendant_heads,
        successor,
    )
    _validate_kernel(contracts["kernel"])

    roots = _module_roots(contracts["module_map"])
    successor_edges: set[tuple[str, str, str, str]] = set()
    if successor:
        nce = successor["nce_additive_successor"]
        overlay = nce["module_overlay"]
        roots = sorted(
            [*roots, (overlay["source_root"].rstrip("/"), overlay["module_code"])],
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        successor_edges = {
            (
                item["source_path"], item["import_name"],
                item["source_module"], item["target_module"],
            )
            for item in nce["authorized_dependency_edges"]
        }
    exception_keys = _exception_keys(contracts["legacy_exceptions"])
    edges: list[ImportEdge] = []
    admitted_unmapped_targets = {
        ("startup.py", "restaurant.customer_channel.router", "restaurant/customer_channel/router.py")
    } if successor else set()
    files = _production_python_files(root_path, contracts["module_map"])
    for path in files:
        relative = path.relative_to(root_path).as_posix()
        edges.extend(
            _edges_for_source(
                root_path,
                relative,
                path.read_text(encoding="utf-8"),
                roots,
                admitted_unmapped_targets,
            )
        )
    violations, used = _evaluate_edges(edges, contracts["dependency_policy"], exception_keys)
    if successor_edges:
        present_successor_edges = {edge.key() for edge in edges if edge.key() in successor_edges}
        if present_successor_edges != successor_edges:
            _fail(
                "PC0-NCE-DEPENDENCY-EDGE-MISSING",
                str(sorted(successor_edges - present_successor_edges)),
            )
        violations = [edge for edge in violations if edge.key() not in successor_edges]
    if violations:
        edge = violations[0]
        _fail("PC0-DEPENDENCY-DENIED", " -> ".join(edge.key()))
    expected_ids = set(exception_keys.values())
    if used != expected_ids:
        _fail("PC0-EXCEPTION-BASELINE-DRIFT", f"unused={sorted(expected_ids-used)}, unknown={sorted(used-expected_ids)}")

    result = {
        "status": "PASS",
        "module_count": len(contracts["module_map"]["modules"]),
        "authority_count": len(contracts["authorities"]["authorities"]),
        "reference_migration_count": len(contracts["reference_migrations"]["entries"]),
        "legacy_exception_count": len(exception_keys),
        "production_python_file_count": len(files),
        "cross_module_edge_count": len(edges),
        "successor_dependency_edge_count": len(successor_edges),
        "nce_source_file_count": len(_NCE_SOURCE_HASHES) if successor else 0,
        "canonical_migration_head": contracts["finance"]["canonical_head"],
    }
    if validate_release:
        manifest = _load_json(root_path, "pc0_release_manifest.json")
        replacements = {
            item["path"]: item for item in successor.get("pc0_release_replacements", [])
        } if successor else {}
        used_replacements: set[str] = set()
        for item in manifest.get("artifacts", []):
            path = root_path / item["path"]
            if not path.is_file():
                _fail("PC0-RELEASE-MANIFEST", item["path"])
            actual = _sha256_file(path)
            if actual == item["sha256"]:
                continue
            replacement = replacements.get(item["path"])
            if not replacement or replacement["historical_sha256"] != item["sha256"] or replacement["successor_sha256"] != actual:
                _fail("PC0-RELEASE-MANIFEST", item["path"])
            used_replacements.add(item["path"])
        if used_replacements != set(replacements):
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", f"unused={sorted(set(replacements)-used_replacements)}")
        result["release_artifact_count"] = len(manifest.get("artifacts", []))
    return result
