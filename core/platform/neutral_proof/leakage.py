"""Context-aware tenant-specific literal leakage scan for active Platform Core."""

from __future__ import annotations

import re
from pathlib import Path


def scan_wnd_leakage(root: Path, policy: dict) -> dict[str, object]:
    allowed = {(item["path"], item["marker"]) for item in policy["allowed_active_references"]}
    findings: list[dict[str, object]] = []
    for source_root in policy["active_roots"]:
        candidate = root / source_root
        paths = sorted(candidate.rglob("*.py")) if candidate.is_dir() else [candidate]
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                for pattern in policy["patterns"]:
                    if re.search(pattern, line, re.IGNORECASE):
                        marker = next((item[1] for item in allowed if item[0] == relative and item[1] in line), None)
                        if marker is None:
                            findings.append({"path": relative, "line": number, "pattern": pattern})
    if findings:
        raise ValueError(f"active_wnd_literal_leakage={findings}")
    return {"status": "PASS", "active_roots": len(policy["active_roots"]), "allowed_proof_guards": len(allowed), "findings": 0}
