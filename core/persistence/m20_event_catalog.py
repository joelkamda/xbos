"""Canonical M2.0 financial-event catalog seed support.

The approved M0 JSON catalog is the semantic authority.  This module turns
that immutable contract into deterministic rows for
``financial_event_type_versions`` and rejects source drift before inserting
anything.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "contracts" / "finance" / "v1" / "financial_event_catalog.json"

CATALOG_CODE = "XBOS_CANONICAL_FINANCIAL_EVENTS"
CATALOG_VERSION = 1
CONTRACT_REVISION = 2
EXPECTED_CATALOG_SEMANTIC_SHA256 = (
    "079cc4c6743c400bc6eb94302a1bf87f1211b8cde70c594043c8b9d15086487c"
)
EXPECTED_EVENT_COUNT = 20

RECONCILIATION_EFFECTS = (
    "inflow",
    "outflow",
    "movement",
    "control_increase",
    "control_decrease",
    "control_reversal",
    "commercial",
    "account_adjustment",
    "none",
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CatalogSeedError(RuntimeError):
    """Raised when the approved seed source or installed rows are unsafe."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the M0-approved canonical JSON representation."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    selected = path or CATALOG_PATH
    return json.loads(selected.read_text(encoding="utf-8"))


def validate_catalog(catalog: dict[str, Any]) -> None:
    identity = (
        catalog.get("catalog_code"),
        catalog.get("catalog_version"),
        catalog.get("contract_revision"),
        catalog.get("status"),
    )
    expected = (CATALOG_CODE, CATALOG_VERSION, CONTRACT_REVISION, "approved")
    if identity != expected:
        raise CatalogSeedError(
            f"Unexpected catalog identity/status: {identity!r}; expected {expected!r}"
        )

    fingerprint = semantic_sha256(catalog)
    if fingerprint != EXPECTED_CATALOG_SEMANTIC_SHA256:
        raise CatalogSeedError(
            "Approved catalog semantic fingerprint mismatch: "
            f"{fingerprint} != {EXPECTED_CATALOG_SEMANTIC_SHA256}"
        )

    events = catalog.get("event_types")
    if not isinstance(events, list) or len(events) != EXPECTED_EVENT_COUNT:
        raise CatalogSeedError(
            f"Expected {EXPECTED_EVENT_COUNT} event definitions; got "
            f"{len(events) if isinstance(events, list) else type(events).__name__}"
        )

    identities = [
        (event.get("event_type_code"), event.get("event_version"))
        for event in events
    ]
    if len(set(identities)) != len(identities):
        raise CatalogSeedError("Event type/version identities are not unique")

    approved_effects = tuple(catalog.get("reconciliation_effects") or ())
    if set(approved_effects) != set(RECONCILIATION_EFFECTS):
        raise CatalogSeedError("Catalog reconciliation vocabulary is unexpected")


def _seed_reconciliation_effect(event: dict[str, Any]) -> str:
    """Resolve the stored default effect without losing dynamic policy.

    Dynamic policies remain verbatim in ``account_role_policy``.  Their static
    column value is the effect for the default economic role when available,
    otherwise ``none`` until the M2 engine resolves the event instance.
    """

    policy = event["reconciliation_policy"]
    mode = policy["mode"]
    if mode == "fixed":
        effect = policy["effect"]
    elif mode == "by_economic_role":
        effect = policy["mappings"][event["default_economic_role"]]
    elif mode in {"inverse_original", "classification_dependent"}:
        effect = "none"
    else:
        raise CatalogSeedError(
            f"Unsupported reconciliation policy mode {mode!r} for "
            f"{event.get('event_type_code')!r}"
        )

    if effect not in RECONCILIATION_EFFECTS:
        raise CatalogSeedError(f"Unapproved reconciliation effect: {effect!r}")
    return effect


def _account_role_policy(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed_economic_roles": event["allowed_economic_roles"],
        "requires_original_event": event["requires_original_event"],
        "source_record_kinds": event["source_record_kinds"],
        "required_classification_roles": event["required_classification_roles"],
        "operational_account_policy": event["operational_account_policy"],
        "reconciliation_policy": event["reconciliation_policy"],
        "posting_profiles": event["posting_profiles"],
    }


def build_seed_rows(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    selected = catalog or load_catalog()
    validate_catalog(selected)
    approved_at = datetime.fromisoformat(selected["approved_at"].replace("Z", "+00:00"))
    catalog_hash = semantic_sha256(selected)

    rows: list[dict[str, Any]] = []
    for event in selected["event_types"]:
        event_hash = semantic_sha256(event)
        if not _HASH_PATTERN.fullmatch(event_hash):
            raise CatalogSeedError("Generated event definition hash is invalid")
        rows.append(
            {
                "event_type_code": event["event_type_code"],
                "event_version": event["event_version"],
                "display_name": event["display_name"],
                "definition": event["definition"],
                "amount_policy": event["amount_policy"],
                "default_economic_role": event["default_economic_role"],
                "reconciliation_effect": _seed_reconciliation_effect(event),
                "account_role_policy": _account_role_policy(event),
                "posting_eligible": event["posting_eligible"],
                "effective_from": approved_at,
                "effective_to": None,
                "approved_at": approved_at,
                "definition_hash": event_hash,
                "metadata": {
                    "catalog_code": selected["catalog_code"],
                    "catalog_version": selected["catalog_version"],
                    "contract_revision": selected["contract_revision"],
                    "catalog_semantic_sha256": catalog_hash,
                    "event_definition": event,
                },
            }
        )
    return rows


_SELECT_EXISTING_SQL = """
    SELECT event_type_code, event_version, definition_hash
    FROM public.financial_event_type_versions
    WHERE event_type_code = :event_type_code AND event_version = :event_version
    """

_INSERT_ROW_SQL = """
    INSERT INTO public.financial_event_type_versions (
        event_type_code, event_version, display_name, definition,
        amount_policy, default_economic_role, reconciliation_effect,
        account_role_policy, posting_eligible, effective_from, effective_to,
        approved_at, definition_hash, metadata
    ) VALUES (
        :event_type_code, :event_version, :display_name, :definition,
        :amount_policy, :default_economic_role, :reconciliation_effect,
        CAST(:account_role_policy AS JSONB), :posting_eligible,
        :effective_from, :effective_to, :approved_at, :definition_hash,
        CAST(:metadata AS JSONB)
    )
    """


def seed_catalog(bind: Any) -> int:
    """Insert missing approved rows and reject conflicting identities."""

    from sqlalchemy import text

    select_existing = text(_SELECT_EXISTING_SQL)
    insert_row = text(_INSERT_ROW_SQL)
    inserted = 0
    for row in build_seed_rows():
        existing = bind.execute(
            select_existing,
            {
                "event_type_code": row["event_type_code"],
                "event_version": row["event_version"],
            },
        ).mappings().one_or_none()
        if existing:
            if existing["definition_hash"] != row["definition_hash"]:
                raise CatalogSeedError(
                    "Conflicting immutable catalog row for "
                    f"{row['event_type_code']} v{row['event_version']}"
                )
            continue

        parameters = dict(row)
        parameters["account_role_policy"] = json.dumps(
            row["account_role_policy"], ensure_ascii=False, sort_keys=True
        )
        parameters["metadata"] = json.dumps(
            row["metadata"], ensure_ascii=False, sort_keys=True
        )
        bind.execute(insert_row, parameters)
        inserted += 1
    return inserted


def seed_identities() -> Iterable[tuple[str, int]]:
    for row in build_seed_rows():
        yield row["event_type_code"], row["event_version"]
