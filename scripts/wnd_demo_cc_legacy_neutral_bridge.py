from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "5c706797029a"
NEUTRAL_BASELINE_REVISION = "m13_source_state_001"
NEUTRAL_VERSION_TABLE = "alembic_neutral_bridge_version"
APPROVED_SOURCE_STATE_SCHEMA_SHA256 = (
    "86e05e04286edaf0dd0c9ea9cb531fd29b6967ce5dccee4b712d5126ede16cab"
)
NEUTRAL_049 = "cc_catalog_binding_price_code_case_049"
NEUTRAL_050 = "cc_order_draft_facade_050"
ALLOWED_TARGETS = frozenset({NEUTRAL_049, NEUTRAL_050})
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class BridgeRejected(RuntimeError):
    pass


def validate_local_database_url(
    database_url: str,
    *,
    expected_database: str,
) -> None:
    url = make_url(database_url)
    host = (url.host or "").casefold()
    if host not in LOCAL_HOSTS:
        raise BridgeRejected("bridge_requires_localhost_database")
    if url.database != expected_database:
        raise BridgeRejected("bridge_database_name_mismatch")
    if url.drivername.split("+", 1)[0] != "postgresql":
        raise BridgeRejected("bridge_requires_postgresql")


def _table_exists(connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name, schema="public")


def _single_revision(connection, table_name: str) -> str | None:
    if not _table_exists(connection, table_name):
        return None
    rows = connection.execute(
        text(f'SELECT version_num FROM public."{table_name}"')
    ).scalars().all()
    if len(rows) != 1:
        raise BridgeRejected(f"{table_name}_must_contain_exactly_one_revision")
    return str(rows[0])


def inspect_bridge_state(database_url: str) -> tuple[str, str | None]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            legacy = _single_revision(connection, "alembic_version")
            if legacy is None:
                raise BridgeRejected("legacy_alembic_version_missing")
            neutral = _single_revision(connection, NEUTRAL_VERSION_TABLE)
            return legacy, neutral
    finally:
        engine.dispose()


def _canonical_source_state_schema_sha256(database_url: str) -> str:
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise BridgeRejected("pg_dump_required_for_source_state_equivalence")
    dump_url = make_url(database_url).set(drivername="postgresql")
    completed = subprocess.run(
        [
            pg_dump,
            "--dbname",
            dump_url.render_as_string(hide_password=False),
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--exclude-table=public.alembic_version",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise BridgeRejected("source_state_schema_dump_failed")
    canonical = completed.stdout.replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def adopt_approved_source_state_baseline(database_url: str) -> str:
    digest = _canonical_source_state_schema_sha256(database_url)
    if digest != APPROVED_SOURCE_STATE_SCHEMA_SHA256:
        raise BridgeRejected("source_state_schema_not_equivalent")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            legacy = _single_revision(connection, "alembic_version")
            if legacy != LEGACY_REVISION:
                raise BridgeRejected("legacy_revision_mismatch")
            if _table_exists(connection, NEUTRAL_VERSION_TABLE):
                raise BridgeRejected("neutral_bridge_version_table_already_exists")
            connection.execute(
                text(
                    f'CREATE TABLE public."{NEUTRAL_VERSION_TABLE}" ('
                    'version_num VARCHAR(128) NOT NULL PRIMARY KEY)'
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO public."{NEUTRAL_VERSION_TABLE}" '
                    '(version_num) VALUES (:revision)'
                ),
                {"revision": NEUTRAL_BASELINE_REVISION},
            )
    finally:
        engine.dispose()

    legacy_after, neutral_after = inspect_bridge_state(database_url)
    if legacy_after != LEGACY_REVISION:
        raise BridgeRejected("legacy_revision_changed_during_baseline_adoption")
    if neutral_after != NEUTRAL_BASELINE_REVISION:
        raise BridgeRejected("neutral_baseline_adoption_failed")
    return digest


@contextmanager
def _neutral_alembic_environment(database_url: str) -> Iterator[None]:
    previous_url = os.environ.get("DATABASE_URL")
    previous_table = os.environ.get("ALEMBIC_NEUTRAL_VERSION_TABLE")
    os.environ["DATABASE_URL"] = database_url
    os.environ["ALEMBIC_NEUTRAL_VERSION_TABLE"] = NEUTRAL_VERSION_TABLE
    try:
        yield
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        if previous_table is None:
            os.environ.pop("ALEMBIC_NEUTRAL_VERSION_TABLE", None)
        else:
            os.environ["ALEMBIC_NEUTRAL_VERSION_TABLE"] = previous_table


def upgrade_bridge(
    database_url: str,
    *,
    target: str,
    expected_database: str,
) -> tuple[str, str]:
    if target not in ALLOWED_TARGETS:
        raise BridgeRejected("bridge_target_not_authorized")

    validate_local_database_url(
        database_url,
        expected_database=expected_database,
    )
    legacy_before, neutral_before = inspect_bridge_state(database_url)
    if legacy_before != LEGACY_REVISION:
        raise BridgeRejected("legacy_revision_mismatch")

    if target == NEUTRAL_050 and neutral_before != NEUTRAL_049:
        raise BridgeRejected("neutral_050_requires_049_gate")
    if target == NEUTRAL_049:
        if neutral_before is None:
            adopt_approved_source_state_baseline(database_url)
            legacy_before, neutral_before = inspect_bridge_state(database_url)
        if neutral_before not in {NEUTRAL_BASELINE_REVISION, NEUTRAL_049}:
            raise BridgeRejected("neutral_049_requires_verified_baseline_or_049")

    if neutral_before != target:
        alembic = Config(str(ROOT / "alembic_neutral.ini"))
        with _neutral_alembic_environment(database_url):
            command.upgrade(alembic, target)

    legacy_after, neutral_after = inspect_bridge_state(database_url)
    if legacy_after != LEGACY_REVISION:
        raise BridgeRejected("legacy_revision_changed")
    if neutral_after != target:
        raise BridgeRejected("neutral_target_not_materialized")
    return legacy_after, neutral_after


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sandbox-only WND legacy -> neutral migration bridge. "
            "Executes real neutral migrations while preserving legacy revision identity."
        )
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--target",
        required=True,
        choices=sorted(ALLOWED_TARGETS),
    )
    parser.add_argument(
        "--expected-database",
        default="wnd_demo_cc_compat_r1",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    legacy, neutral = upgrade_bridge(
        args.database_url,
        target=args.target,
        expected_database=args.expected_database,
    )
    print(f"LEGACY_REVISION_POST={legacy}")
    print(f"NEUTRAL_BRIDGE_REVISION_POST={neutral}")
    print(f"FALSE_STAMP_USED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
