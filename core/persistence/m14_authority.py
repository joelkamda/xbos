"""M1.4 canonical Alembic authority activation policy.

The policy intentionally supports one isolated local development database.
Production and parity adoption require a later rollout authorization.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from sqlalchemy.engine import URL, make_url


SOURCE_AUTHORITY_REVISION = "5c706797029a"
SOURCE_STATE_REVISION = "m13_source_state_001"
CANONICAL_HEAD_REVISION = "m13_financial_foundation_002"

ACTIVE_SCRIPT_LOCATION = "%(here)s/alembic_neutral"
INACTIVE_SCRIPT_LOCATION = "%(here)s/alembic"
SAFE_INI_URL = "driver://unused"

ACTIVATION_DATABASE = "xbos_track_b_dev"
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

FOUNDATION_TABLES = frozenset(
    {
        "organization_units",
        "currency_assets",
        "tenant_currency_policies",
        "business_cycle_policies",
        "kernel_source_records",
        "financial_counterparties",
        "operational_financial_accounts",
        "payment_provider_accounts",
        "idempotency_records",
        "financial_event_type_versions",
        "financial_events",
        "financial_event_taxonomy",
        "outbox_messages",
        "historical_transformation_runs",
        "historical_transformation_exceptions",
    }
)


def checked_activation_url(value: str | URL) -> URL:
    url = value if isinstance(value, URL) else make_url(value)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Canonical authority activation requires PostgreSQL")
    if url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(f"Refusing non-local PostgreSQL host: {url.host!r}")
    if url.database != ACTIVATION_DATABASE:
        raise RuntimeError(
            f"Refusing database other than {ACTIVATION_DATABASE!r}: {url.database!r}"
        )
    return url


def source_tables_from_baseline(path: Path) -> frozenset[str]:
    if not path.is_file():
        raise RuntimeError(f"Approved source-state SQL is missing: {path}")
    names = re.findall(
        r"CREATE\s+TABLE\s+public\.([a-z][a-z0-9_]*)\s*\(",
        path.read_text(encoding="utf-8"),
        flags=re.IGNORECASE,
    )
    if not names or len(names) != len(set(names)):
        raise RuntimeError("Source-state table inventory is empty or ambiguous")
    # The approved schema asset deliberately excludes Alembic's mutable
    # control table. A managed source database must still contain it, so the
    # authority inventory accounts for it explicitly rather than weakening
    # business-table comparison.
    return frozenset({*(name.lower() for name in names), "alembic_version"})


def assert_exact_source_schema(actual: Iterable[str], expected: Iterable[str]) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    missing = expected_set - actual_set
    unexpected = actual_set - expected_set
    if missing or unexpected:
        raise RuntimeError(
            "Source-state schema mismatch: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
