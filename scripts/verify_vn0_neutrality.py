"""VN0 shared-runtime neutrality conformance; PC6 remains independent.

Checks executable authority signatures rather than blanket WND string counts.
Read-only: no filesystem mutation, DB access, imports of application modules,
or provider calls. Keep intentional restaurant/compatibility/proof ancestry.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOTS = (
    "core/api/orders",
    "core/domain/orders",
    "core/domain/inventory",
    "core/platform",
    "core/integrations",
)
BOOT_FILES = ("main.py", "app.py", "startup.py", "database.py", "settings.py")
ALLOWED_PATH_PREFIXES = (
    "core/platform/neutral_proof/",  # PC6 proof (its own frozen scanner)
)
WNDPOLICY_MODULES = (
    "restaurant.wnd_operational_policy",
    "restaurant.operational_policy_binding",
    "restaurant.r6.wnd_api_compat",
)
RESTAURANT_MENU_TERMS = frozenset({
    "towel", "ndole", "eru", "gari", "red bull", "main dish",
    "hot drinks", "soft drinks", "beer", "breakfast",
})
# Only terms in an executable category-routing decision / classification
# construct count. Text in comments, exception messages and documentation does not.
IDENTITY_TERMS = frozenset({"wnd", "wine & dine", "wine-and-dine", "wine_dine"})
ROUTING_SYMBOLS = frozenset({"KITCHEN_ROUTE_NAMES", "NON_KITCHEN_ROUTE_NAMES"})
AUTHORITY_NAMES = frozenset({"tenant_id", "tenant_code", "tenant_name", "tenant", "code"})
FAMILY_NAMES = frozenset({"family", "inventory_family", "category", "segment", "family_name"})
NEGATIVE_NAMES = frozenset({"allow_negative_stock", "allow_negative", "allow_negative_food"})


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    code: str


def _strings(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {x.value.casefold() for x in ast.walk(node)
            if isinstance(x, ast.Constant) and isinstance(x.value, str)}


def _names(node: ast.AST) -> set[str]:
    names = {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}
    names.update(x.attr for x in ast.walk(node) if isinstance(x, ast.Attribute))
    return names


def _is_true_decision(node: ast.AST) -> bool:
    # Only examine the immediate decision body, not unrelated nested branches.
    for item in node.body:
        if isinstance(item, ast.Return) and isinstance(item.value, ast.Constant) and item.value.value is True:
            return True
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            if any(_names(t) & NEGATIVE_NAMES for t in targets):
                if isinstance(item.value, ast.Constant) and item.value.value is True:
                    return True
    return False


def _scan_python(source: str, path: str) -> list[Finding]:
    tree = ast.parse(source, filename=path)
    issues: set[Finding] = set()
    is_inventory = path.startswith("core/domain/inventory/")
    is_orders = path.startswith(("core/api/orders/", "core/domain/orders/"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == prefix or alias.name.startswith(prefix + ".")
                       for prefix in WNDPOLICY_MODULES):
                    issues.add(Finding(path, node.lineno, "DIRECT_WND_POLICY_IMPORT"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module == prefix or module.startswith(prefix + ".")
                   for prefix in WNDPOLICY_MODULES):
                issues.add(Finding(path, node.lineno, "DIRECT_WND_POLICY_IMPORT"))
        if isinstance(node, (ast.If, ast.IfExp)):
            condition = node.test
            consts = _strings(condition)
            names = _names(condition)
            if "wnd.logpom" in consts:
                issues.add(Finding(path, node.lineno, "WND_PROFILE_SELECTION_IN_SHARED_RUNTIME"))
            if consts & IDENTITY_TERMS and (names & AUTHORITY_NAMES):
                issues.add(Finding(path, node.lineno, "WND_TENANT_IDENTITY_BRANCH"))
            if (names & {"tenant_id"}) and any(
                isinstance(x, ast.Constant) and type(x.value) is int and x.value == 2
                for x in ast.walk(condition)
            ):
                issues.add(Finding(path, node.lineno, "HARDCODED_TENANT_TWO_BRANCH"))
            if is_inventory and consts & {"kitchen", "food", "bar", "drinks"} and names & FAMILY_NAMES:
                if isinstance(node, ast.If) and _is_true_decision(node):
                    issues.add(Finding(path, node.lineno, "IMPLICIT_RESTAURANT_NEGATIVE_STOCK"))
            if is_orders and consts & RESTAURANT_MENU_TERMS and names & {"category", "subcategory", "names_upper", "fulfillment"}:
                issues.add(Finding(path, node.lineno, "RESTAURANT_FULFILLMENT_ROUTING"))
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_names = set().union(*(_names(t) for t in targets))
            value = node.value
            if is_orders and target_names & ROUTING_SYMBOLS:
                issues.add(Finding(path, node.lineno, "RESTAURANT_ROUTE_CONSTANT_IN_CORE"))
            if is_inventory and target_names & {"FOOD_KEYWORDS", "DRINK_KEYWORDS", "WINE_KEYWORDS"}:
                issues.add(Finding(path, node.lineno, "RESTAURANT_KEYWORD_CONSTANT_IN_CORE"))
            if is_inventory and _strings(value) & RESTAURANT_MENU_TERMS and target_names & {
                "keywords", "aliases", "menu_aliases", "FOOD_KEYWORDS", "DRINK_KEYWORDS", "classification",
            }:
                issues.add(Finding(path, node.lineno, "WND_ALIAS_AUTHORITY_IN_SHARED_INVENTORY"))
            if is_inventory and target_names & NEGATIVE_NAMES:
                if isinstance(value, ast.Compare) and "kitchen" in _strings(value):
                    issues.add(Finding(path, node.lineno, "IMPLICIT_RESTAURANT_NEGATIVE_STOCK"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.casefold() == "wnd.logpom":
                issues.add(Finding(path, node.lineno, "WND_PROFILE_SELECTOR_IN_CORE"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"import_module", "__import__"} and _strings(node) & set(WNDPOLICY_MODULES):
                issues.add(Finding(path, node.lineno, "DYNAMIC_WND_POLICY_IMPORT"))
    return sorted(issues)


def scan(root: Path = ROOT) -> list[Finding]:
    root = Path(root)
    files: set[Path] = set()
    for area in SHARED_ROOTS:
        directory = root / area
        if directory.is_dir():
            files.update(directory.rglob("*.py"))
    for file in BOOT_FILES:
        path = root / file
        if path.is_file():
            files.add(path)
    findings: list[Finding] = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if any(relative.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
            continue
        findings.extend(_scan_python(path.read_text(encoding="utf-8-sig"), relative))
    return sorted(set(findings))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    findings = scan(args.root)
    print(json.dumps({
        "conformance": "xbos.vn0.shared-runtime-neutrality.v1",
        "result": "PASS" if not findings else "FAIL",
        "blocking_count": len(findings),
        "violations": [asdict(f) for f in findings],
        "scanned_zones": list(SHARED_ROOTS) + list(BOOT_FILES),
        "allowed_explicit_zone": list(ALLOWED_PATH_PREFIXES),
        "pc6_preserved": True,
    }, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
