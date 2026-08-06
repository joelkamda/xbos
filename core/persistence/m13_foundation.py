"""M1.3 neutral financial foundation and lineage-adoption policy.

This module is deliberately side-effect free. It does not import application
models, open a connection, mutate Alembic state, or activate canonical writes.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Iterable

from sqlalchemy.engine import URL, make_url


SOURCE_STATE_REVISION = "m13_source_state_001"
FOUNDATION_REVISION = "m13_financial_foundation_002"
SOURCE_AUTHORITY_REVISION = "5c706797029a"

FRESH_REHEARSAL_DATABASE = "xbos_track_b_m13_fresh_test"
ADOPTION_REHEARSAL_DATABASE = "xbos_track_b_m13_adoption_test"
ALLOWED_REHEARSAL_DATABASES = frozenset(
    {FRESH_REHEARSAL_DATABASE, ADOPTION_REHEARSAL_DATABASE}
)
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

FOUNDATION_TABLES = (
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
)

APPEND_ONLY_TABLES = frozenset(
    {
        "financial_event_type_versions",
        "financial_events",
        "financial_event_taxonomy",
    }
)

REQUIRED_COMPOSITE_TENANT_KEYS = frozenset(
    {
        "organization_units",
        "business_cycle_policies",
        "kernel_source_records",
        "financial_counterparties",
        "operational_financial_accounts",
        "payment_provider_accounts",
        "financial_events",
        "users",
        "taxonomy_nodes",
    }
)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_rehearsal_url(base_url: str | URL, database_name: str) -> URL:
    url = make_url(str(base_url)) if not isinstance(base_url, URL) else base_url
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("M1.3 rehearsal requires PostgreSQL")
    if url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(f"Refusing non-local PostgreSQL host: {url.host!r}")
    if database_name not in ALLOWED_REHEARSAL_DATABASES:
        raise RuntimeError(f"Refusing unapproved rehearsal database: {database_name!r}")
    return url.set(database=database_name)


def assert_exact_table_set(actual: Iterable[str]) -> None:
    missing = set(FOUNDATION_TABLES) - set(actual)
    if missing:
        raise AssertionError(f"Missing M1.3 foundation tables: {sorted(missing)}")
