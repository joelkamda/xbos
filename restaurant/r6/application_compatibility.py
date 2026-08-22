"""R6.3 WND reference-application compatibility helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Mapping, Any


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def openapi_route_set(schema: Mapping[str, Any]) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for path, operations in (schema.get("paths") or {}).items():
        if not isinstance(operations, Mapping):
            continue
        for method in operations:
            m = str(method).upper()
            if m in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                routes.add((m, str(path)))
    return routes


def assert_required_routes(
    schema: Mapping[str, Any],
    required: Iterable[Mapping[str, str]],
) -> None:
    actual = openapi_route_set(schema)
    missing = []
    for row in required:
        key = (str(row["method"]).upper(), str(row["path"]))
        if key not in actual:
            missing.append(f"{key[0]} {key[1]}")
    if missing:
        raise ValueError("missing WND reference API routes: " + ", ".join(sorted(missing)))


def schema_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    normalized = [
        {
            "table": str(row["table_name"]),
            "column": str(row["column_name"]),
            "type": str(row["data_type"]),
            "nullable": str(row["is_nullable"]),
            "default": None if row.get("column_default") is None else str(row["column_default"]),
        }
        for row in rows
    ]
    normalized.sort(key=lambda x: (x["table"], x["column"]))
    return semantic_hash(normalized)


def validate_uat_evidence(evidence: Mapping[str, Any], matrix: Mapping[str, Any]) -> None:
    if evidence.get("status") != "PASS":
        raise ValueError("visual UAT status is not PASS")
    expected_ids = [row["id"] for row in matrix["items"]]
    actual = evidence.get("items") or {}
    if set(actual) != set(expected_ids):
        raise ValueError("visual UAT item set does not match frozen matrix")
    failed = [item for item in expected_ids if actual.get(item) != "PASS"]
    if failed:
        raise ValueError("visual UAT contains non-PASS items: " + ",".join(failed))
