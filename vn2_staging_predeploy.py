"""VN2-only private deployment and schema gate. Never logs credentials."""
import ipaddress
import os
import socket
import subprocess
import sys
from urllib.parse import urlsplit, unquote

from sqlalchemy import create_engine, text

DB_NAME = "xafpay_xbos_neutral_vn2_staging"
DB_RESOURCE_ID = "dpg-db8u70favr4c73ccf5n0-a"
REVISION = "browser_session_v1_051"
COLUMNS = {"session_id", "user_id", "tenant_id", "branch_id", "created_at",
           "expires_at", "revoked_at", "revocation_reason", "current_refresh_jti",
           "previous_refresh_jti", "previous_refresh_valid_until", "last_rotated_at"}
INDEXES = {"ix_xbos_browser_sessions_user", "ix_xbos_browser_sessions_expiry"}
DEPENDENCIES = {"tenants", "branches", "users", "pk_packs", "pk_pack_versions",
                "pk_tenant_pack_installations", "pk_templates", "pk_template_versions",
                "pk_template_pack_requirements", "pk_tenant_template_bindings"}


class AdmissionDenied(RuntimeError):
    pass


def target_url(env=None):
    env = os.environ if env is None else env
    if env.get("XBOS_VN2_STAGING_PROFILE") != "enabled":
        raise AdmissionDenied("VN2_PROFILE_MISSING")
    raw = env.get("DATABASE_URL")
    host = env.get("XBOS_VN2_EXPECTED_PRIVATE_DB_HOST")
    if not raw or not host or env.get("XBOS_VN2_EXPECTED_DATABASE_ID") != DB_RESOURCE_ID:
        raise AdmissionDenied("VN2_TARGET_CONFIG_MISSING")
    # Host must be provisioned independently from exact Render private metadata.
    # Never derive an assumed hostname from the database ID or the URL itself.
    if not host.strip() or host != host.strip():
        raise AdmissionDenied("VN2_PRIVATE_HOST_UNVERIFIED")
    try:
        p = urlsplit(raw)
        if (p.scheme not in ("postgresql", "postgresql+psycopg2")
                or p.hostname != host or p.port != 5432
                or unquote(p.path) != "/" + DB_NAME
                or p.query or p.fragment or p.username is None or not p.password):
            raise AdmissionDenied("VN2_DATABASE_IDENTITY_MISMATCH")
    except (ValueError, TypeError) as exc:
        raise AdmissionDenied("VN2_DATABASE_URL_INVALID") from exc
    return raw


def security_config(env=None):
    env = os.environ if env is None else env
    if not env.get("JWT_SECRET") or not env.get("JWT_ALGORITHM"):
        raise AdmissionDenied("VN2_JWT_MISSING")
    if env.get("XBOS_BROWSER_ALLOWED_ORIGINS") != "https://xafpay-xbos-neutral-vn2-staging.netlify.app":
        raise AdmissionDenied("VN2_ORIGIN_MISMATCH")


def check_schema(conn, ready=True):
    ver = int(conn.execute(text("SHOW server_version_num")).scalar_one())
    if ver // 10000 != 17:
        raise AdmissionDenied("VN2_POSTGRES_VERSION_MISMATCH")
    db = conn.execute(text("SELECT current_database()")).scalar_one()
    if db != DB_NAME:
        raise AdmissionDenied("VN2_DATABASE_MISMATCH")
    tables = set(conn.execute(text(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"
    )).scalars())
    if not ready:
        objects = int(conn.execute(text(
            "SELECT count(*) FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public'"
        )).scalar_one())
        other_clients = int(conn.execute(text(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE datname=current_database() AND pid <> pg_backend_pid()"
        )).scalar_one())
        if tables or objects or other_clients:
            raise AdmissionDenied("VN2_PRESTATE_NONEMPTY_OR_ACTIVE")
        return
    if "alembic_version" not in tables:
        raise AdmissionDenied("VN2_ALEMBIC_MISSING")
    versions = list(conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars())
    if versions != [REVISION]:
        raise AdmissionDenied("VN2_REVISION_MISMATCH")
    if "xbos_browser_sessions" not in tables or not DEPENDENCIES.issubset(tables):
        raise AdmissionDenied("VN2_SCHEMA_TABLE_MISSING")
    cols = set(conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='xbos_browser_sessions'"
    )).scalars())
    if cols != COLUMNS:
        raise AdmissionDenied("VN2_SESSION_COLUMNS_MISMATCH")
    indexes = set(conn.execute(text(
        "SELECT indexname FROM pg_catalog.pg_indexes "
        "WHERE schemaname='public' AND tablename='xbos_browser_sessions'"
    )).scalars())
    if not INDEXES.issubset(indexes):
        raise AdmissionDenied("VN2_SESSION_INDEX_MISSING")


def require_private_route(url):
    # Render-private DNS must resolve only to non-public, non-loopback addresses.
    parsed = urlsplit(url)
    private_ranges = tuple(ipaddress.ip_network(cidr) for cidr in
        ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
         "100.64.0.0/10", "fc00::/7"))
    try:
        answers = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(item[4][0]) for item in answers]
    except (OSError, ValueError, TypeError) as exc:
        raise AdmissionDenied("VN2_PRIVATE_DNS_UNAVAILABLE") from exc
    if not addresses or any(not any(ip in network for network in private_ranges)
                            for ip in addresses):
        raise AdmissionDenied("VN2_NONPRIVATE_NETWORK_REJECTED")


def check_database(url, ready=True):
    # No connect to public IPs, even if a URL and expected host are identical.
    require_private_route(url)
    # Strictly read-only transaction; no schema creation or implicit fallback.
    engine = create_engine(url, connect_args={"connect_timeout": 5}, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            check_schema(conn, ready=ready)
    finally:
        engine.dispose()


def predeploy():
    url = target_url()
    security_config()
    check_database(url, ready=False)
    # One subprocess invocation, no retry. Database URL is inherited in-process.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini",
         "upgrade", REVISION], check=False, timeout=180, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AdmissionDenied("VN2_ALEMBIC_FAILED")
    check_database(url, ready=True)


def main():
    try:
        predeploy()
    except Exception:
        # All error messages are fixed codes; never expose SQL, URL, or secrets.
        print("VN2_PREDEPLOY_DENIED", file=sys.stderr)
        return 1
    print("VN2_PREDEPLOY_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
