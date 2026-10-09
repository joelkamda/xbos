from __future__ import annotations

import argparse
import base64
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
APPROVED_EXECUTABLE_DDL_SHA256 = (
    "a4c33b2bbb8e1a804084376bf0798b096606860888009f756a809d3ba58c9f64"
)
APPROVED_OWNER_NEUTRAL_CATALOG_SHA256 = (
    "adaa44b54496a7e109a7a8ee9332ea483fcf46401098c8a7ce4d6c343621162f"
)
APPROVED_LOGICAL_OBJECT_ROWS = 557
REFERENCE_OWNER_PRESERVED = False
PORTABLE_RESTRICT_KEY = "XafPayR3R3PortableGate20261009"
NEUTRAL_049 = "cc_catalog_binding_price_code_case_049"
NEUTRAL_050 = "cc_order_draft_facade_050"
ALLOWED_TARGETS = frozenset({NEUTRAL_049, NEUTRAL_050})
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

PORTABLE_CATALOG_SQL = """
SELECT object_type,object_name,detail FROM (
SELECT 'SCHEMA'::text AS object_type,n.nspname::text AS object_name,encode(convert_to(pg_get_userbyid(n.nspowner),'UTF8'),'base64') AS detail
FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'TABLE',n.nspname||'.'||c.relname,encode(convert_to(concat_ws(';',c.relkind::text,pg_get_userbyid(c.relowner),c.relpersistence::text,c.relispartition::text),'UTF8'),'base64')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'COLUMN',n.nspname||'.'||c.relname||'.'||a.attname,encode(convert_to(concat_ws(';',a.attnum::text,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull::text,a.attidentity::text,a.attgenerated::text,COALESCE(pg_get_expr(d.adbin,d.adrelid),''),COALESCE(coll.collname,'')),'UTF8'),'base64')
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum LEFT JOIN pg_collation coll ON coll.oid=a.attcollation
WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'CONSTRAINT',n.nspname||'.'||c.relname||'.'||con.conname,encode(convert_to(concat_ws(';',con.contype::text,pg_get_constraintdef(con.oid,true),con.condeferrable::text,con.condeferred::text,con.convalidated::text),'UTF8'),'base64')
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE con.contype IN ('p','u','f','c') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'INDEX',ns.nspname||'.'||idx.relname,encode(convert_to(concat_ws(';',tbl.relname,i.indisunique::text,i.indisprimary::text,i.indisvalid::text,i.indisready::text,pg_get_indexdef(i.indexrelid)),'UTF8'),'base64')
FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid JOIN pg_class tbl ON tbl.oid=i.indrelid JOIN pg_namespace ns ON ns.oid=tbl.relnamespace WHERE ns.nspname NOT LIKE 'pg_%' AND ns.nspname<>'information_schema'
UNION ALL
SELECT 'SEQUENCE',n.nspname||'.'||c.relname,encode(convert_to(concat_ws(';',pg_get_userbyid(c.relowner),pg_catalog.format_type(s.seqtypid,NULL),s.seqstart::text,s.seqincrement::text,s.seqmax::text,s.seqmin::text,s.seqcache::text,s.seqcycle::text),'UTF8'),'base64')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_sequence s ON s.seqrelid=c.oid WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'SEQ_OWNERSHIP',ns_seq.nspname||'.'||seq.relname,encode(convert_to(concat_ws(';',COALESCE(ns_tbl.nspname,''),COALESCE(tbl.relname,''),COALESCE(att.attname,''),COALESCE(dep.deptype::text,'')),'UTF8'),'base64')
FROM pg_class seq JOIN pg_namespace ns_seq ON ns_seq.oid=seq.relnamespace LEFT JOIN pg_depend dep ON dep.classid='pg_class'::regclass AND dep.objid=seq.oid AND dep.refclassid='pg_class'::regclass AND dep.deptype IN ('a','i') LEFT JOIN pg_class tbl ON tbl.oid=dep.refobjid LEFT JOIN pg_namespace ns_tbl ON ns_tbl.oid=tbl.relnamespace LEFT JOIN pg_attribute att ON att.attrelid=tbl.oid AND att.attnum=dep.refobjsubid
WHERE seq.relkind='S' AND ns_seq.nspname NOT LIKE 'pg_%' AND ns_seq.nspname<>'information_schema'
UNION ALL
SELECT 'ENUM',n.nspname||'.'||t.typname||'.'||e.enumsortorder::text,encode(convert_to(e.enumlabel,'UTF8'),'base64')
FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace JOIN pg_enum e ON e.enumtypid=t.oid WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'FUNCTION',n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',encode(convert_to(concat_ws(';',pg_get_function_result(p.oid),l.lanname,p.provolatile::text,p.prosecdef::text,p.proisstrict::text,p.proparallel::text,pg_get_userbyid(p.proowner),pg_get_functiondef(p.oid)),'UTF8'),'base64')
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'TRIGGER',n.nspname||'.'||c.relname||'.'||t.tgname,encode(convert_to(concat_ws(';',t.tgenabled::text,pg_get_triggerdef(t.oid,true)),'UTF8'),'base64')
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
UNION ALL
SELECT 'EXTENSION',e.extname,encode(convert_to(concat_ws(';',e.extversion,n.nspname,e.extrelocatable::text),'UTF8'),'base64')
FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
) x ORDER BY 1,2,3
"""


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


def _canonical_executable_ddl_bytes(dump_bytes: bytes) -> bytes:
    normalized = dump_bytes.replace(b"\r\n", b"\n")
    executable: list[bytes] = []
    for line in normalized.split(b"\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(b"--"):
            continue
        if stripped.startswith(b"\\restrict ") or stripped.startswith(b"\\unrestrict "):
            continue
        executable.append(line)
    return b"\n".join(executable) + b"\n"


def _executable_ddl_sha256(database_url: str) -> str:
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
            f"--restrict-key={PORTABLE_RESTRICT_KEY}",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise BridgeRejected("source_state_schema_dump_failed")
    canonical = _canonical_executable_ddl_bytes(completed.stdout)
    return hashlib.sha256(canonical).hexdigest()


def _owner_neutral_detail(
    object_type: str,
    object_name: str,
    detail: str,
) -> tuple[str, str | None]:
    if object_type == "SCHEMA":
        return "<OWNER>", detail
    if object_type == "TABLE":
        parts = detail.split(";")
        if len(parts) != 4:
            raise BridgeRejected("portable_catalog_table_shape_invalid")
        owner = parts[1]
        parts[1] = "<OWNER>"
        return ";".join(parts), owner
    if object_type == "SEQUENCE":
        parts = detail.split(";")
        if len(parts) != 8:
            raise BridgeRejected("portable_catalog_sequence_shape_invalid")
        owner = parts[0]
        parts[0] = "<OWNER>"
        return ";".join(parts), owner
    if object_type == "FUNCTION":
        parts = detail.split(";", 7)
        if len(parts) != 8:
            raise BridgeRejected("portable_catalog_function_shape_invalid")
        if parts[3].casefold() != "false":
            raise BridgeRejected(
                "portable_catalog_owner_neutralization_security_definer_forbidden:"
                + object_name
            )
        owner = parts[6]
        parts[6] = "<OWNER>"
        return ";".join(parts), owner
    return detail, None


def _owner_neutral_catalog_sha256(
    database_url: str,
) -> tuple[str, int, str]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            tx = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(text(PORTABLE_CATALOG_SQL)).mappings().all()
            tx.rollback()
    finally:
        engine.dispose()

    portable_rows: list[tuple[str, str, str]] = []
    owner_provenance: list[tuple[str, str, str]] = []
    for row in rows:
        object_type = str(row["object_type"])
        object_name = str(row["object_name"])
        encoded = str(row["detail"])
        try:
            detail = base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:
            raise BridgeRejected("portable_catalog_detail_decode_failed") from exc
        portable_detail, owner = _owner_neutral_detail(
            object_type,
            object_name,
            detail,
        )
        portable_rows.append((object_type, object_name, portable_detail))
        if owner is not None:
            owner_provenance.append((object_type, object_name, owner))

    portable_rows.sort(key=lambda row: (row[0], row[1], row[2]))
    owner_provenance.sort(key=lambda row: (row[0], row[1], row[2]))
    payload = (
        "\n".join(f"{t}|{n}|{d}" for t, n, d in portable_rows) + "\n"
    ).encode("utf-8")
    owner_payload = (
        "\n".join(f"{t}|{n}|{o}" for t, n, o in owner_provenance) + "\n"
    ).encode("utf-8")
    return (
        hashlib.sha256(payload).hexdigest(),
        len(portable_rows),
        hashlib.sha256(owner_payload).hexdigest(),
    )


def _portable_source_state_gate(database_url: str) -> str:
    if REFERENCE_OWNER_PRESERVED:
        raise BridgeRejected("portable_contract_reference_owner_state_invalid")
    executable_digest = _executable_ddl_sha256(database_url)
    catalog_digest, row_count, owner_provenance_digest = (
        _owner_neutral_catalog_sha256(database_url)
    )
    if executable_digest != APPROVED_EXECUTABLE_DDL_SHA256:
        raise BridgeRejected("source_state_executable_ddl_not_equivalent")
    if row_count != APPROVED_LOGICAL_OBJECT_ROWS:
        raise BridgeRejected("source_state_logical_object_set_not_equivalent")
    if catalog_digest != APPROVED_OWNER_NEUTRAL_CATALOG_SHA256:
        raise BridgeRejected("source_state_portable_catalog_not_equivalent")
    print(f"PORTABLE_EXECUTABLE_DDL_SHA256={executable_digest}", flush=True)
    print(f"PORTABLE_LOGICAL_OBJECT_ROWS={row_count}", flush=True)
    print(f"PORTABLE_OWNER_NEUTRAL_CATALOG_SHA256={catalog_digest}", flush=True)
    print(f"OWNER_PROVENANCE_SHA256={owner_provenance_digest}", flush=True)
    print("PORTABLE_MATERIAL_DELTA_COUNT=0", flush=True)
    print("PORTABLE_SOURCE_STATE_EQUIVALENCE=PASS", flush=True)
    return executable_digest


def adopt_approved_source_state_baseline(database_url: str) -> str:
    digest = _portable_source_state_gate(database_url)

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
    print("FALSE_STAMP_USED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
