"""Loads and validates the frozen M7.0 legacy financial authority inventory."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from .legacy_authority_contract import (
    LegacyAuthorityError,
    LegacyAuthorityInventory,
    LegacyAuthoritySurface,
    inventory_fingerprint,
)

EXPECTED_HEAD = "m64_reconciliation_controls_020"
EXPECTED_BRANCH = "track-b/m7-finance-facing-wnd-migration-support"
EXPECTED_COMMIT = "9ccddd3"


def _symbols(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.add(node.name)
        elif isinstance(node, ast.ClassDef):
            found.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.add(f"{node.name}.{child.name}")
    return found


def load_inventory(root: Path, *, validate_sources: bool = True) -> LegacyAuthorityInventory:
    path = root / "contracts/finance/v1/m70_legacy_financial_authority_inventory_and_adapter_boundary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyAuthorityError("invalid_inventory_json", str(path)) from exc
    if payload.get("contract_code") != "XBOS_M70_LEGACY_FINANCIAL_AUTHORITY_INVENTORY_AND_ADAPTER_BOUNDARY":
        raise LegacyAuthorityError("unexpected_contract", repr(payload.get("contract_code")))
    checkpoint = payload.get("source_checkpoint", {})
    if checkpoint != {"branch": EXPECTED_BRANCH, "commit": EXPECTED_COMMIT}:
        raise LegacyAuthorityError("unexpected_checkpoint", repr(checkpoint))
    if payload.get("canonical_head") != EXPECTED_HEAD or payload.get("migration") is not False:
        raise LegacyAuthorityError("unexpected_head_or_migration", repr(payload.get("canonical_head")))
    if payload.get("writer_routing") != "unchanged" or payload.get("live_cutover_owner") != "R6":
        raise LegacyAuthorityError("cutover_boundary_changed", "writer routing or owner")
    surfaces = tuple(LegacyAuthoritySurface.from_mapping(value) for value in payload.get("surfaces", ()))
    codes = tuple(surface.code for surface in surfaces)
    if len(codes) != len(set(codes)):
        raise LegacyAuthorityError("duplicate_surface", repr(codes))
    if set(codes) != set(payload.get("required_surface_codes", ())):
        raise LegacyAuthorityError("inventory_incomplete", repr(codes))
    if validate_sources:
        for surface in surfaces:
            source_path = root / surface.source_path
            try:
                source = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise LegacyAuthorityError("missing_source", surface.source_path) from exc
            if surface.source_symbol not in _symbols(source):
                raise LegacyAuthorityError("missing_source_symbol", f"{surface.source_path}:{surface.source_symbol}")
            for marker in surface.evidence_markers:
                if marker not in source:
                    raise LegacyAuthorityError("missing_evidence_marker", f"{surface.code}:{marker}")
    return LegacyAuthorityInventory(
        canonical_head=payload["canonical_head"],
        writer_routing=payload["writer_routing"],
        live_cutover_owner=payload["live_cutover_owner"],
        adapter_mode=payload["adapter_mode"],
        surfaces=surfaces,
        semantic_fingerprint=inventory_fingerprint(payload),
    )


def verify_no_writer_rerouting(root: Path) -> None:
    legacy_roots = (root / "core/domain/accounting", root / "core/domain/sales", root / "core/domain/payments", root / "core/domain/inventory", root / "core/api")
    forbidden = ("legacy_authority_inventory", "wnd_finance_adapter_contract")
    for base in legacy_roots:
        for path in base.rglob("*.py"):
            if path.parts[-3:] == ("domain", "finance", path.name):
                continue
            source = path.read_text(encoding="utf-8")
            if any(marker in source for marker in forbidden):
                raise LegacyAuthorityError("writer_rerouted", str(path.relative_to(root)))
