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


def _validate_composition(root: Path, composition: dict[str, Any]) -> None:
    if composition.get("fingerprint_mode") != "sha256_git_canonical_lf":
        _fail("PC0-COMPOSITION-FINGERPRINT-MODE", str(composition.get("fingerprint_mode")))
    for relative, expected in composition.get("files", {}).items():
        actual = _source_sha256(root / relative)
        if actual != expected:
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


def _validate_finance(root: Path, finance: dict[str, Any], inventory: dict[str, Any], accepted_heads: Iterable[str] = ()) -> None:
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
        if item.get("owner") not in {"PC1", "SO1", "SO2", "SO3"} or not all(isinstance(item.get(key), str) and item[key] for key in ("root","path","sha256")):
            _fail("PC0-NON-FINANCE-EXTENSION", str(item))
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
    _validate_modules(contracts["module_map"], contracts["dependency_policy"], contracts["interfaces"])
    if set(contracts["composition"].get("files", {})) != set(contracts["module_map"].get("composition_files", [])):
        _fail("PC0-COMPOSITION-COVERAGE", "composition baseline must exactly match the module-map inventory")
    _validate_authorities(contracts["authorities"])
    _validate_reference_migrations(contracts["reference_migrations"])
    _validate_composition(root_path, contracts["composition"])
    descendant_heads = [
        contracts["pc1"].get("accepted_head"), contracts["pc2"].get("accepted_head"),
        contracts["pc3"].get("accepted_head"), contracts["pc4"].get("accepted_head"),
        contracts["pc5"].get("accepted_head"),
    ]
    so1_contract = root_path / "contracts/shared_operations/v1/so1_authority.json"
    if so1_contract.is_file():
        descendant_heads.append(json.loads(so1_contract.read_text(encoding="utf-8")).get("accepted_head"))
    so2_contract = root_path / "contracts/shared_operations/v1/so2_authority.json"
    if so2_contract.is_file():
        descendant_heads.append(json.loads(so2_contract.read_text(encoding="utf-8")).get("accepted_head"))
    so3_contract = root_path / "contracts/shared_operations/v1/so3_authority.json"
    if so3_contract.is_file():
        descendant_heads.append(json.loads(so3_contract.read_text(encoding="utf-8")).get("accepted_head"))
    _validate_finance(
        root_path,
        contracts["finance"],
        contracts["finance_inventory"],
        descendant_heads,
    )
    _validate_kernel(contracts["kernel"])

    roots = _module_roots(contracts["module_map"])
    exception_keys = _exception_keys(contracts["legacy_exceptions"])
    edges: list[ImportEdge] = []
    files = _production_python_files(root_path, contracts["module_map"])
    for path in files:
        relative = path.relative_to(root_path).as_posix()
        edges.extend(_edges_for_source(root_path, relative, path.read_text(encoding="utf-8"), roots))
    violations, used = _evaluate_edges(edges, contracts["dependency_policy"], exception_keys)
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
        "canonical_migration_head": contracts["finance"]["canonical_head"],
    }
    if validate_release:
        manifest = _load_json(root_path, "pc0_release_manifest.json")
        for item in manifest.get("artifacts", []):
            path = root_path / item["path"]
            if not path.is_file() or _sha256_file(path) != item["sha256"]:
                _fail("PC0-RELEASE-MANIFEST", item["path"])
        result["release_artifact_count"] = len(manifest.get("artifacts", []))
    return result
