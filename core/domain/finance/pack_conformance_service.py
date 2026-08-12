"""Evaluation and static-boundary checks for neutral pack conformance."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from .pack_conformance_contract import (
    CONTRACT_CODE, CONTRACT_VERSION, PackConformanceError,
    PackConformanceProfile, PackReadinessReport,
)

PROTECTED_TABLES = frozenset({
    "financial_events", "journal_entries", "journal_lines", "financial_obligations",
    "value_sources", "payment_allocations", "allocation_reversals", "payment_settlements",
    "reconciliation_windows", "reconciliation_window_governance_events", "reconciliation_controls",
    "outbox_messages", "idempotency_records",
})
_MUTATION = re.compile(r"\b(?:insert\s+into|update|delete\s+from)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)


def _string_literals(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise PackConformanceError("pack_source_not_parseable", str(exc)) from exc
    return tuple(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str))


def find_hidden_financial_writers(root: Path, relative_paths: Iterable[str]) -> tuple[str, ...]:
    findings: list[str] = []
    for relative in sorted(set(relative_paths)):
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PackConformanceError("pack_source_unreadable", relative) from exc
        for literal in _string_literals(source):
            for match in _MUTATION.finditer(literal):
                if match.group(1).lower() in PROTECTED_TABLES:
                    findings.append(f"{relative}:{match.group(1).lower()}")
    return tuple(sorted(set(findings)))


def evaluate_pack(profile: PackConformanceProfile) -> PackReadinessReport:
    return PackReadinessReport(
        pack_code=profile.pack_code,
        pack_version=profile.pack_version,
        conformance_contract=CONTRACT_CODE,
        conformance_version=CONTRACT_VERSION,
        profile_fingerprint=profile.profile_fingerprint,
        covered_sources=profile.authoritative_sources,
        covered_flows=tuple(item.flow_code for item in profile.flows),
        readiness_verdict="PASS",
    )


def validate_generic_harness_neutrality(root: Path) -> None:
    for relative in (
        "core/domain/finance/pack_conformance_contract.py",
        "core/domain/finance/pack_conformance_service.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        if any(name.rsplit(".", 1)[-1].startswith("wnd_") for name in imports):
            raise PackConformanceError("industry_profile_imported_by_generic_harness", relative)
