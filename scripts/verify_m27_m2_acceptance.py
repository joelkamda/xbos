"""M2.7 acceptance runner for the frozen canonical financial event engine."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from core.domain.finance.m2_acceptance import (
    EXPECTED_HEAD,
    load_release_manifest,
    validate_release_manifest,
)
from database import engine as application_engine


DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _database_url(database_name: str):
    return _application_url().set(database=database_name)


def _admin_engine():
    return create_engine(
        _database_url("postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True
    )


def _exists(database_name: str) -> bool:
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                    {"database_name": database_name},
                ).scalar_one_or_none()
            )
    finally:
        engine.dispose()


def _capabilities() -> tuple[dict[str, str], ...]:
    manifest = load_release_manifest(ROOT)
    return tuple(manifest["capability_verifiers"])


def _development_counts() -> tuple[str | None, dict[str, int]]:
    selected = _application_url().database
    if selected != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"refusing development verification against {selected!r}")
    expected = load_release_manifest(ROOT)["development_acceptance_counts"]
    with application_engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one_or_none()
        counts = {
            name: int(
                connection.execute(
                    text(f"SELECT count(*) FROM public.{name}")
                ).scalar_one()
            )
            for name in expected
        }
    return revision, counts


def _verify_development() -> dict[str, int]:
    revision, counts = _development_counts()
    expected = load_release_manifest(ROOT)["development_acceptance_counts"]
    if revision != EXPECTED_HEAD:
        raise RuntimeError(f"expected development revision {EXPECTED_HEAD}, found {revision}")
    if counts != expected:
        raise RuntimeError(f"development acceptance counts differ: {counts!r}")
    return counts


def _verify_static_and_development() -> None:
    result = validate_release_manifest(ROOT)
    counts = _verify_development()
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={result.canonical_head}")
    print(f"frozen_contract_components={result.checked_components}")
    print(f"canonical_migration_revisions={len(result.lineage)}")
    for name, count in counts.items():
        print(f"{name}={count}")
    print(
        "m27_m2_development_acceptance=PASS "
        f"canonical_head={EXPECTED_HEAD} manifest=PASS development_empty=PASS"
    )


def _status() -> None:
    for capability in _capabilities():
        database = capability["database"]
        print(f"database={database} exists={str(_exists(database)).lower()}")


def _run_capability(capability: dict[str, str]) -> None:
    database = capability["database"]
    if _exists(database):
        raise RuntimeError(f"disposable database already exists: {database}")
    checkpoint = capability["checkpoint_commit"]
    with tempfile.TemporaryDirectory(prefix="xbos_m2_acceptance_") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "checkpoint.zip"
        snapshot = temporary_root / "snapshot"
        archived = subprocess.run(
            [
                "git",
                "archive",
                "--format=zip",
                f"--output={archive}",
                checkpoint,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if archived.returncode != 0:
            raise RuntimeError(
                f"cannot materialize {capability['phase']} checkpoint {checkpoint}: "
                f"{archived.stderr.strip()}"
            )
        snapshot.mkdir()
        with zipfile.ZipFile(archive) as checkpoint_zip:
            checkpoint_zip.extractall(snapshot)
        script = snapshot / capability["script"]
        if not script.is_file():
            raise RuntimeError(f"checkpoint omitted capability verifier: {script}")
        child_environment = os.environ.copy()
        child_environment["DATABASE_URL"] = _application_url().render_as_string(
            hide_password=False
        )
        completed = subprocess.run(
            [sys.executable, str(script), "create-and-verify"],
            cwd=snapshot,
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
        )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{capability['phase']} verifier failed with exit code {completed.returncode}; "
            f"inspect retained database={database}"
        )
    if capability["pass_token"] not in completed.stdout:
        raise RuntimeError(f"{capability['phase']} verifier omitted its PASS token")
    if _exists(database):
        raise RuntimeError(f"{capability['phase']} retained disposable database={database}")


def _create_and_verify() -> None:
    validate_release_manifest(ROOT)
    _verify_development()
    capabilities = _capabilities()
    unexpected = [item["database"] for item in capabilities if _exists(item["database"])]
    if unexpected:
        raise RuntimeError(f"unexpected disposable databases exist: {unexpected!r}")
    for capability in capabilities:
        _run_capability(capability)
    validate_release_manifest(ROOT)
    _verify_development()
    print(
        "m27_m2_acceptance=PASS "
        f"canonical_head={EXPECTED_HEAD} manifest=PASS development_empty=PASS "
        "m20=PASS m21=PASS m22=PASS m23=PASS m24=PASS m25=PASS m26=PASS "
        "disposable_databases_dropped=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    args = parser.parse_args()

    if args.command == "status":
        _status()
    elif args.command == "verify":
        _verify_static_and_development()
    else:
        _create_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
