"""Dependency-free validators for future Shared Operations module declarations."""

from __future__ import annotations

from typing import Any, Mapping


class SOConstitutionError(ValueError):
    """A proposed Shared Operations contract violates SO0 law."""


MODULE_CODES = frozenset(f"SO{number}" for number in range(1, 11))
REQUIRED_MODULE_FIELDS = (
    "module_code", "name", "capability_codes", "public_commands", "public_queries",
    "operational_facts", "platform_authorities", "finance_integration_points",
    "required_permissions", "configuration_dependencies", "semantic_dependencies",
    "xa_hooks", "lifecycle", "pack_declaration_hooks", "ownership_classification",
)
XA_HOOKS = frozenset({
    "navigation", "actions", "work_queue", "configuration", "dashboard",
    "documents", "search", "offline",
})
PRIVATE_SEGMENTS = frozenset({"repository", "repositories", "persistence", "sql", "private"})


def validate_module_declaration(value: Mapping[str, Any]) -> Mapping[str, Any]:
    missing = [field for field in REQUIRED_MODULE_FIELDS if field not in value]
    if missing:
        raise SOConstitutionError(f"module_declaration_missing={','.join(missing)}")
    module = value["module_code"]
    if module not in MODULE_CODES:
        raise SOConstitutionError(f"unknown_module={module}")
    if not value["capability_codes"] or len(value["capability_codes"]) != len(set(value["capability_codes"])):
        raise SOConstitutionError(f"invalid_capabilities={module}")
    if not set(value["xa_hooks"]).issubset(XA_HOOKS):
        raise SOConstitutionError(f"unknown_xa_hook={module}")
    required_authorities = set(value["platform_authorities"])
    if not {"PC1", "PC3", "PC4", "PC5"}.issubset(required_authorities):
        raise SOConstitutionError(f"mandatory_platform_authorities_missing={module}")
    if value["ownership_classification"] != "shared_operations":
        raise SOConstitutionError(f"ownership_classification_invalid={module}")
    lifecycle = value["lifecycle"]
    if not {"contract_version", "status"}.issubset(lifecycle):
        raise SOConstitutionError(f"lifecycle_incomplete={module}")
    return value


def evaluate_private_import(source_module: str, imported_path: str) -> str | None:
    """Return a stable denial code for an SO cross-module private import."""
    source = source_module.upper()
    parts = imported_path.replace("/", ".").split(".")
    target = next((part.upper() for part in parts if part.upper() in MODULE_CODES), None)
    if source not in MODULE_CODES or target is None or source == target:
        return None
    if PRIVATE_SEGMENTS.intersection(part.casefold() for part in parts):
        return "SO0-CROSS-MODULE-PRIVATE-IMPORT"
    if "contracts" not in {part.casefold() for part in parts} or "public" not in {part.casefold() for part in parts}:
        return "SO0-CROSS-MODULE-NONPUBLIC-IMPORT"
    return None
