"""P0D R5C: default-off, nonpublic WND startup authorization projection.

This module is intentionally operator-invoked only through the application startup
hook registered by startup.py. It exposes no HTTP surface and performs no writes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

TENANT_ID = 910001
GENERATION = "p0d-r5c-r0"
EXPECTED_RENDER_SERVICE_ID = "srv-db3vej67bikc73ai2080"
EXPECTED_RENDER_HOST = "wnd-xafpay-demo-austin-backend.onrender.com"
EXPECTED_RENDER_BRANCH = "compat/wnd-demo-cc-r1-legacy-neutral-bridge"
EXPECTED_DATABASE = "wnd_xafpay_demo_austin_db"
EXPECTED_DATABASE_USER = "wnd_xafpay_demo_austin_db_user"
SERVICE_CODE = "customer-channel"
SERVICE_CREDENTIAL_REFERENCE = "env.xafpay_customer_channel_service_token"
CHECKOUT_PERMISSION = "restaurant.customer_channel.checkout"
CONTEXT_PURPOSE = CHECKOUT_PERMISSION

ENABLE_ENV = "XAFPAY_P0D_R5C_WND_STARTUP_DIAGNOSTIC_ENABLED"
EXPIRES_ENV = "XAFPAY_P0D_R5C_WND_STARTUP_DIAGNOSTIC_EXPIRES_AT"
MAX_GATE_TTL = timedelta(minutes=10)

_REQUIRED_TABLES = (
    "tenants",
    "pa_merchants",
    "legacy_branch_structural_mappings",
    "organization_units",
    "locations",
    "service_identities",
    "scoped_role_assignments",
    "authorization_roles",
    "authorization_role_permissions",
    "permission_definitions",
    "ia0_interaction_context_bindings",
    "restaurant_customer_catalog_read_bindings",
    "r1_restaurant_service_modes",
)
_WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
_LOGGER = logging.getLogger("xbos.p0d_r5c")
_ONCE_LOCK = threading.Lock()
_ONCE_CLAIMED = False


class ProjectionHold(RuntimeError):
    """Safe internal control-flow hold; message must be a predefined label."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_expiry(raw: str | None) -> datetime | None:
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _gate(environ: Mapping[str, str], now: datetime) -> str:
    flag = str(environ.get(ENABLE_ENV, "")).strip()
    if not flag or flag == "0":
        return "DISABLED"
    if flag != "1":
        return "HOLD_FLAG_INVALID"

    expires = _parse_expiry(environ.get(EXPIRES_ENV))
    if expires is None or expires <= now or expires - now > MAX_GATE_TTL:
        return "HOLD_GATE_EXPIRED_OR_OVERSCOPED"

    expected = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": EXPECTED_RENDER_SERVICE_ID,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": EXPECTED_RENDER_HOST,
        "RENDER_GIT_BRANCH": EXPECTED_RENDER_BRANCH,
    }
    for key, value in expected.items():
        if str(environ.get(key, "")).strip() != value:
            return "HOLD_RUNTIME_CONTEXT"
    return "PASS"


def _base_result(gate: str) -> dict[str, str]:
    return {
        "generation": GENERATION,
        "gate": gate,
        "reader": "NOT_RUN",
        "schema": "NOT_RUN",
        "tenant": "HOLD_UNPROVEN",
        "merchant": "HOLD_UNPROVEN",
        "structure": "HOLD_UNPROVEN",
        "service_identity": "HOLD_UNPROVEN",
        "service_assignment": "HOLD_UNPROVEN",
        "checkout_permission": "HOLD_UNPROVEN",
        "checkout_context": "HOLD_UNPROVEN",
        "catalog": "HOLD_UNPROVEN",
    }


def _emit(result: Mapping[str, str]) -> None:
    allowed = {
        "generation",
        "gate",
        "reader",
        "schema",
        "tenant",
        "merchant",
        "structure",
        "service_identity",
        "service_assignment",
        "checkout_permission",
        "checkout_context",
        "catalog",
    }
    safe = {key: str(result[key]) for key in allowed if key in result}
    _LOGGER.warning(
        "P0D_R5C_WND_STARTUP_PROJECTION %s",
        json.dumps(safe, sort_keys=True, separators=(",", ":")),
    )


def _claim_once() -> bool:
    global _ONCE_CLAIMED
    with _ONCE_LOCK:
        if _ONCE_CLAIMED:
            return False
        _ONCE_CLAIMED = True
        return True


def _identity_metadata(connection) -> Mapping[str, Any]:
    return connection.execute(
        text(
            """
            /* r5c:identity */
            SELECT
              current_database() = :expected_database AS database_ok,
              current_user = :expected_user AS current_user_ok,
              session_user = :expected_user AS session_user_ok,
              r.rolsuper,
              r.rolbypassrls,
              r.rolcreaterole,
              r.rolcreatedb,
              r.rolreplication,
              has_database_privilege(current_user,current_database(),'CREATE') AS database_create,
              has_schema_privilege(current_user,'public','CREATE') AS schema_create
            FROM pg_roles r
            WHERE r.rolname=current_user
            """
        ),
        {
            "expected_database": EXPECTED_DATABASE,
            "expected_user": EXPECTED_DATABASE_USER,
        },
    ).mappings().one()


def _table_metadata(connection, table_name: str) -> Mapping[str, Any]:
    if table_name not in _REQUIRED_TABLES:
        raise ProjectionHold("HOLD_SCHEMA_DRIFT")
    qualified = f"public.{table_name}"
    return connection.execute(
        text(
            """
            /* r5c:table-metadata */
            SELECT
              to_regclass(:qualified) IS NOT NULL AS exists_ok,
              CASE WHEN to_regclass(:qualified) IS NULL THEN false
                   ELSE has_table_privilege(current_user,:qualified,'SELECT') END AS select_ok,
              CASE WHEN to_regclass(:qualified) IS NULL THEN false
                   ELSE (
                     has_table_privilege(current_user,:qualified,'INSERT') OR
                     has_table_privilege(current_user,:qualified,'UPDATE') OR
                     has_table_privilege(current_user,:qualified,'DELETE') OR
                     has_table_privilege(current_user,:qualified,'TRUNCATE') OR
                     has_table_privilege(current_user,:qualified,'REFERENCES') OR
                     has_table_privilege(current_user,:qualified,'TRIGGER')
                   ) END AS write_effective,
              COALESCE((
                SELECT pg_get_userbyid(c.relowner)=current_user
                FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname=:table_name
                LIMIT 1
              ),false) AS owned_by_current_user
            """
        ),
        {"qualified": qualified, "table_name": table_name},
    ).mappings().one()


def _grade_exact_one(value: int) -> str:
    if value == 0:
        return "ABSENT"
    if value == 1:
        return "PASS"
    return "AMBIGUOUS"


def _stage_two(connection, *, tenant_id: int, at: datetime) -> dict[str, str]:
    if tenant_id != TENANT_ID:
        raise ProjectionHold("HOLD_TENANT_REFUSED")

    result: dict[str, str] = {}

    tenant_count = int(
        connection.execute(
            text(
                """
                /* r5c:tenant */
                SELECT count(*)
                FROM tenants
                WHERE id=:tenant AND lifecycle_state='active'
                """
            ),
            {"tenant": TENANT_ID},
        ).scalar_one()
    )
    result["tenant"] = _grade_exact_one(tenant_count)

    merchant_count = int(
        connection.execute(
            text(
                """
                /* r5c:merchant */
                SELECT count(*)
                FROM pa_merchants
                WHERE tenant_id=:tenant AND administration_state='operational'
                """
            ),
            {"tenant": TENANT_ID},
        ).scalar_one()
    )
    result["merchant"] = _grade_exact_one(merchant_count)

    structure = connection.execute(
        text(
            """
            /* r5c:structure */
            SELECT
              count(*) AS mapping_count,
              count(DISTINCT m.branch_id) AS branch_count,
              count(DISTINCT m.location_id) AS location_count,
              count(DISTINCT m.organization_unit_id) AS organization_count
            FROM legacy_branch_structural_mappings m
            JOIN locations l
              ON l.tenant_id=m.tenant_id AND l.id=m.location_id AND l.active=true
            JOIN organization_units o
              ON o.tenant_id=m.tenant_id AND o.id=m.organization_unit_id AND o.active=true
            WHERE m.tenant_id=:tenant
            """
        ),
        {"tenant": TENANT_ID},
    ).mappings().one()
    mapping_count = int(structure["mapping_count"])
    if mapping_count == 0:
        result["structure"] = "ABSENT"
    elif (
        mapping_count == 1
        and int(structure["branch_count"]) == 1
        and int(structure["location_count"]) == 1
        and int(structure["organization_count"]) == 1
    ):
        result["structure"] = "PASS"
    else:
        result["structure"] = "AMBIGUOUS"

    service_count = int(
        connection.execute(
            text(
                """
                /* r5c:service-identity */
                SELECT count(*)
                FROM service_identities
                WHERE tenant_id=:tenant
                  AND service_code=:service
                  AND owner_module='restaurant'
                  AND status='active'
                  AND revoked_at IS NULL
                  AND credential_reference=:credential
                """
            ),
            {
                "tenant": TENANT_ID,
                "service": SERVICE_CODE,
                "credential": SERVICE_CREDENTIAL_REFERENCE,
            },
        ).scalar_one()
    )
    result["service_identity"] = _grade_exact_one(service_count)

    assignment = connection.execute(
        text(
            """
            /* r5c:service-assignment */
            SELECT
              count(DISTINCT a.id) AS assignment_count,
              count(DISTINCT a.scope_id) AS location_count,
              count(DISTINCT s.id) AS identity_count
            FROM service_identities s
            JOIN scoped_role_assignments a
              ON a.principal_id=s.id
             AND a.actor_type='service'
             AND a.tenant_id=s.tenant_id
            JOIN authorization_roles r
              ON r.id=a.role_id AND r.status='active'
            WHERE s.tenant_id=:tenant
              AND s.service_code=:service
              AND s.owner_module='restaurant'
              AND s.status='active'
              AND s.revoked_at IS NULL
              AND s.credential_reference=:credential
              AND a.status='active'
              AND a.scope_type='location'
              AND a.scope_id IS NOT NULL
              AND a.valid_from<=:at
              AND (a.valid_to IS NULL OR :at<a.valid_to)
            """
        ),
        {
            "tenant": TENANT_ID,
            "service": SERVICE_CODE,
            "credential": SERVICE_CREDENTIAL_REFERENCE,
            "at": at,
        },
    ).mappings().one()
    assignments = int(assignment["assignment_count"])
    if assignments == 0:
        result["service_assignment"] = "ABSENT"
    elif int(assignment["identity_count"]) == 1 and int(assignment["location_count"]) == 1:
        result["service_assignment"] = "PASS"
    else:
        result["service_assignment"] = "AMBIGUOUS"

    permission = connection.execute(
        text(
            """
            /* r5c:checkout-permission */
            SELECT
              count(*) AS path_count,
              count(DISTINCT s.id) AS identity_count,
              count(DISTINCT a.scope_id) AS location_count
            FROM service_identities s
            JOIN scoped_role_assignments a
              ON a.principal_id=s.id
             AND a.actor_type='service'
             AND a.tenant_id=s.tenant_id
            JOIN authorization_roles r
              ON r.id=a.role_id AND r.status='active'
            JOIN authorization_role_permissions rp
              ON rp.role_id=r.id
             AND rp.effective_from<=:at
             AND (rp.effective_to IS NULL OR :at<rp.effective_to)
            JOIN permission_definitions p
              ON p.id=rp.permission_id
            WHERE s.tenant_id=:tenant
              AND s.service_code=:service
              AND s.owner_module='restaurant'
              AND s.status='active'
              AND s.revoked_at IS NULL
              AND s.credential_reference=:credential
              AND a.status='active'
              AND a.scope_type='location'
              AND a.scope_id IS NOT NULL
              AND a.valid_from<=:at
              AND (a.valid_to IS NULL OR :at<a.valid_to)
              AND p.permission_code=:permission
              AND p.owner_module='restaurant'
              AND p.resource_code='customer_channel'
              AND p.action_code='checkout'
              AND p.status='active'
              AND p.required_assurance=1
              AND 'location'=ANY(p.allowed_scopes)
            """
        ),
        {
            "tenant": TENANT_ID,
            "service": SERVICE_CODE,
            "credential": SERVICE_CREDENTIAL_REFERENCE,
            "permission": CHECKOUT_PERMISSION,
            "at": at,
        },
    ).mappings().one()
    paths = int(permission["path_count"])
    if paths == 0:
        result["checkout_permission"] = "ABSENT"
    elif int(permission["identity_count"]) == 1 and int(permission["location_count"]) == 1:
        result["checkout_permission"] = "PASS"
    else:
        result["checkout_permission"] = "AMBIGUOUS"

    context_count = int(
        connection.execute(
            text(
                """
                /* r5c:checkout-context */
                SELECT count(*)
                FROM ia0_interaction_context_bindings
                WHERE tenant_id=:tenant
                  AND purpose_code=:purpose
                  AND effective_from<=:at
                  AND ended_at IS NULL
                  AND (expires_at IS NULL OR :at<expires_at)
                """
            ),
            {"tenant": TENANT_ID, "purpose": CONTEXT_PURPOSE, "at": at},
        ).scalar_one()
    )
    result["checkout_context"] = _grade_exact_one(context_count)

    catalog = connection.execute(
        text(
            """
            /* r5c:catalog */
            SELECT
              count(DISTINCT b.id) AS binding_count,
              count(DISTINCT m.id) AS merchant_count,
              count(DISTINCT l.id) AS location_count,
              (
                SELECT count(*)
                FROM r1_restaurant_service_modes sm
                WHERE sm.tenant_id=:tenant
                  AND sm.active=true
                  AND sm.mode_code IN ('dine_in','takeaway','delivery')
              ) AS active_mode_count
            FROM restaurant_customer_catalog_read_bindings b
            JOIN pa_merchants m
              ON m.tenant_id=b.tenant_id
             AND m.public_id=b.merchant_public_id
             AND m.administration_state='operational'
            JOIN locations l
              ON l.tenant_id=b.tenant_id
             AND l.id=b.location_id
             AND l.active=true
            WHERE b.tenant_id=:tenant
              AND b.active=true
              AND b.effective_from<=:at
              AND (b.effective_to IS NULL OR :at<b.effective_to)
              AND b.scope_type='location'
              AND b.scope_id=b.location_id
              AND b.price_code='retail'
              AND b.currency='XAF'
            """
        ),
        {"tenant": TENANT_ID, "at": at},
    ).mappings().one()
    bindings = int(catalog["binding_count"])
    if bindings == 0:
        result["catalog"] = "ABSENT"
    elif (
        bindings == 1
        and int(catalog["merchant_count"]) == 1
        and int(catalog["location_count"]) == 1
        and int(catalog["active_mode_count"]) >= 1
    ):
        result["catalog"] = "PASS"
    else:
        result["catalog"] = "AMBIGUOUS"

    return result


def run_projection(engine, *, at: datetime | None = None) -> dict[str, str]:
    now = (at or _utc_now()).astimezone(timezone.utc)
    result = _base_result("PASS")

    previous_connect_timeout = os.environ.get("PGCONNECT_TIMEOUT")
    os.environ["PGCONNECT_TIMEOUT"] = "3"
    transaction = None
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '2500ms'"))
            connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '4000ms'"))

            identity = _identity_metadata(connection)
            identity_ok = (
                bool(identity["database_ok"])
                and bool(identity["current_user_ok"])
                and bool(identity["session_user_ok"])
            )
            if not identity_ok:
                result["reader"] = "HOLD_DB_IDENTITY"
                result["schema"] = "HOLD_UNPROVEN"
                return result

            role_overbroad = any(
                bool(identity[key])
                for key in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreaterole",
                    "rolcreatedb",
                    "rolreplication",
                    "database_create",
                    "schema_create",
                )
            )

            missing = False
            no_select = False
            table_overbroad = False
            for table_name in _REQUIRED_TABLES:
                metadata = _table_metadata(connection, table_name)
                missing = missing or not bool(metadata["exists_ok"])
                no_select = no_select or not bool(metadata["select_ok"])
                table_overbroad = table_overbroad or bool(metadata["write_effective"])
                table_overbroad = table_overbroad or bool(metadata["owned_by_current_user"])

            if missing:
                result["schema"] = "HOLD_SCHEMA_DRIFT"
                result["reader"] = "HOLD_UNPROVEN"
                return result
            result["schema"] = "PASS"

            if no_select:
                result["reader"] = "HOLD_SELECT_DENIED"
                return result
            if role_overbroad or table_overbroad:
                result["reader"] = "HOLD_OVERBROAD_READER"
                return result

            result["reader"] = "PASS"
            result.update(_stage_two(connection, tenant_id=TENANT_ID, at=now))
            return result
    except ProjectionHold as exc:
        result["reader"] = str(exc)
        return result
    except Exception:  # noqa: BLE001 - fail closed without logging raw DB errors.
        result["reader"] = "HOLD_DATABASE_FAILURE"
        if result["schema"] == "NOT_RUN":
            result["schema"] = "HOLD_UNPROVEN"
        return result
    finally:
        if transaction is not None and getattr(transaction, "is_active", True):
            try:
                transaction.rollback()
            except Exception:  # noqa: BLE001 - cleanup must not take the app down.
                result["reader"] = "HOLD_CLEANUP_FAILURE"
        if previous_connect_timeout is None:
            os.environ.pop("PGCONNECT_TIMEOUT", None)
        else:
            os.environ["PGCONNECT_TIMEOUT"] = previous_connect_timeout


def run_startup_diagnostic(
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    engine: Any | None = None,
    emit: Callable[[Mapping[str, str]], None] | None = None,
    enforce_once: bool = True,
) -> dict[str, str]:
    environment = os.environ if environ is None else environ
    selected_now = (now or _utc_now()).astimezone(timezone.utc)
    gate = _gate(environment, selected_now)
    result = _base_result(gate)
    sink = emit or _emit

    if gate != "PASS":
        sink(result)
        return result

    if enforce_once and not _claim_once():
        result["gate"] = "HOLD_ALREADY_EXECUTED"
        sink(result)
        return result

    try:
        if engine is None:
            from database import engine as application_engine

            engine = application_engine
        result = run_projection(engine, at=selected_now)
    except Exception:  # noqa: BLE001 - startup must remain available on HOLD.
        result = _base_result("PASS")
        result["reader"] = "HOLD_INTERNAL"
        result["schema"] = "HOLD_UNPROVEN"

    sink(result)
    return result


def register_startup_diagnostic(app) -> None:
    """Register exactly one nonpublic startup hook; never add an HTTP route."""

    app.add_event_handler("startup", run_startup_diagnostic)


# R5F is deliberately NOT registered by register_startup_diagnostic().
# It cannot use the application's default DB engine and is never hosted-executable
# under the local-only provenance guard. R5C behavior above is unchanged.
R5F_LOCAL_ENABLE = "XAFPAY_R5F_LOCAL_FAKE_METADATA_ENABLED"
R5F_LOCAL_EXPIRES = "XAFPAY_R5F_LOCAL_FAKE_METADATA_EXPIRES_AT"
R5F_MAX_TTL = timedelta(minutes=10)
R5F_EXPECTED_COUNT = len(_REQUIRED_TABLES)

# Exactly one parameterless catalog SELECT. Names are frozen, not constructed from
# caller input. No SELECT of any target relation, tenant, order or credential data.
_R5F_FIXED_CATALOG_SQL = """
/* r5f:fixed-local-pg-catalog-metadata-only */
WITH targets(name) AS (
 VALUES ('tenants'), ('pa_merchants'), ('legacy_branch_structural_mappings'),
 ('organization_units'), ('locations'), ('service_identities'),
 ('scoped_role_assignments'), ('authorization_roles'),
 ('authorization_role_permissions'), ('permission_definitions'),
 ('ia0_interaction_context_bindings'),
 ('restaurant_customer_catalog_read_bindings'),
 ('r1_restaurant_service_modes')
),
roleinfo AS (
 SELECT oid, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb,
        rolreplication, rolinherit
 FROM pg_catalog.pg_roles WHERE rolname = current_user
),
relations AS (
 SELECT t.name, c.oid, c.relowner, c.relrowsecurity, c.relforcerowsecurity,
        COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'SELECT'),false)
          AS can_select,
        (COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'INSERT'),false)
         OR COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'UPDATE'),false)
         OR COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'DELETE'),false)
         OR COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'TRUNCATE'),false)
         OR COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'REFERENCES'),false)
         OR COALESCE(pg_catalog.has_table_privilege(current_user,c.oid,'TRIGGER'),false))
          AS can_write,
        (SELECT count(*) FROM pg_catalog.pg_policy pol WHERE pol.polrelid=c.oid)
          AS policy_count
 FROM targets t
 LEFT JOIN pg_catalog.pg_namespace n ON n.nspname='public'
 LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
    AND c.relname=t.name AND c.relkind IN ('r','p')
),
memberships AS (
 SELECT count(*) AS direct_count
 FROM pg_catalog.pg_auth_members m
 WHERE m.member=(SELECT oid FROM roleinfo)
),
totals AS (
 SELECT count(*) AS target_count,
        count(*) FILTER (WHERE oid IS NULL) AS missing_count,
        count(*) FILTER (WHERE relowner=(SELECT oid FROM roleinfo)) AS owned_count,
        count(*) FILTER (WHERE can_select) AS select_count,
        count(*) FILTER (WHERE can_write) AS write_count,
        count(*) FILTER (WHERE relrowsecurity IS TRUE) AS rls_count,
        count(*) FILTER (WHERE relforcerowsecurity IS TRUE) AS force_rls_count,
        COALESCE(sum(policy_count),0)::bigint AS policy_count
 FROM relations
)
SELECT
  current_user = session_user AS session_identity_match,
  EXISTS (SELECT 1 FROM roleinfo) AS role_exists,
  COALESCE((SELECT rolsuper FROM roleinfo),true) AS is_super,
  COALESCE((SELECT rolbypassrls FROM roleinfo),true) AS bypass_rls,
  COALESCE((SELECT rolcreaterole FROM roleinfo),true) AS create_role,
  COALESCE((SELECT rolcreatedb FROM roleinfo),true) AS create_db_role,
  COALESCE((SELECT rolreplication FROM roleinfo),true) AS replicate,
  COALESCE((SELECT rolinherit FROM roleinfo),true) AS inherits,
  pg_catalog.has_database_privilege(current_user,current_database(),'CREATE')
     AS database_create,
  pg_catalog.has_schema_privilege(current_user,'public','CREATE')
     AS schema_create,
  (SELECT count(*) FROM pg_catalog.pg_database d
    WHERE d.datname=current_database() AND d.datdba=(SELECT oid FROM roleinfo))
     AS owned_database_count,
  (SELECT count(*) FROM pg_catalog.pg_namespace n
    WHERE n.nspname='public' AND n.nspowner=(SELECT oid FROM roleinfo))
     AS owned_schema_count,
  memberships.direct_count AS direct_memberships,
  totals.target_count, totals.missing_count, totals.owned_count,
  totals.select_count, totals.write_count, totals.rls_count,
  totals.force_rls_count, totals.policy_count
FROM memberships CROSS JOIN totals
"""

_R5F_COUNTER_KEYS = (
    "direct_memberships", "target_count", "missing_count", "owned_count",
    "select_count", "write_count", "rls_count", "force_rls_count",
    "policy_count", "owned_database_count", "owned_schema_count",
)
_R5F_BOOLEAN_KEYS = (
    "session_identity_match", "role_exists", "is_super", "bypass_rls",
    "create_role", "create_db_role", "replicate", "inherits",
    "database_create", "schema_create",
)


def r5f_local_gate(
    engine: Any,
    *,
    environ: Mapping[str, str] | None,
    now: datetime,
) -> str:
    """Fail before DB connection unless explicitly isolated localhost fake PG17."""
    if environ is None or environ.get(R5F_LOCAL_ENABLE) != "1":
        return "DISABLED"
    expiry = _parse_expiry(environ.get(R5F_LOCAL_EXPIRES))
    if expiry is None or not now < expiry <= now + R5F_MAX_TTL:
        return "HOLD_EXPIRED"
    if any(
        environ.get(key)
        for key in (
            "RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_HOSTNAME",
            "DATABASE_URL", "RENDER_POSTGRESQL_URL", "PGHOST",
        )
    ):
        return "HOLD_HOSTED_CONTEXT"
    url = getattr(engine, "url", None)
    if (
        url is None
        or getattr(url, "drivername", "") not in
            ("postgresql", "postgresql+psycopg2", "postgresql+psycopg")
        or getattr(url, "host", "") != "127.0.0.1"
        or not isinstance(getattr(url, "port", None), int)
        or getattr(url, "port", None) in (5432, 8001)
        or not (1024 <= getattr(url, "port", 0) <= 65535)
        or not str(getattr(url, "database", "")).startswith("r5f_fixture_")
        or not str(getattr(url, "username", "")).startswith("r5f_")
        or getattr(url, "password", None) is not None
    ):
        return "HOLD_NONLOCAL_ENGINE"
    return "PASS"


def run_r5f_local_metadata(
    engine: Any,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, str | int]:
    """One local fake-only catalog SELECT; no startup registration or logging.

    Never call from the deployed WND application. This is NOT an admitted
    hosted writer exception, hosted reader, or tenant-isolation proof.
    """
    at = (now or _utc_now()).astimezone(timezone.utc)
    result: dict[str, str | int] = {
        "generation": "p0d-r5f-local-r0",
        "gate": r5f_local_gate(engine, environ=environ, now=at),
        "metadata": "NOT_RUN",
        "reader": "HOLD_UNPROVEN",
        "tenant_isolation": "HOLD_UNPROVEN",
    }
    if result["gate"] != "PASS":
        return result

    transaction = None
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='2000ms'"))
            connection.execute(text("SET LOCAL lock_timeout='500ms'"))
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout='3000ms'"))
            row = connection.execute(text(_R5F_FIXED_CATALOG_SQL)).mappings().one()
            counts: dict[str, int] = {}
            for key in _R5F_COUNTER_KEYS:
                value = row[key]
                if type(value) is not int or not 0 <= value <= 100:
                    raise ProjectionHold("HOLD_OUTPUT_BOUNDS")
                counts[key] = value
            flags: dict[str, bool] = {}
            for key in _R5F_BOOLEAN_KEYS:
                if type(row[key]) is not bool:
                    raise ProjectionHold("HOLD_OUTPUT_BOUNDS")
                flags[key] = row[key]
            if (
                counts["target_count"] != R5F_EXPECTED_COUNT
                or counts["missing_count"] > R5F_EXPECTED_COUNT
                or any(
                    counts[key] > R5F_EXPECTED_COUNT
                    for key in (
                        "owned_count", "select_count", "write_count",
                        "rls_count", "force_rls_count",
                    )
                )
            ):
                raise ProjectionHold("HOLD_SCHEMA_BOUNDS")

            result["metadata"] = "PASS" if counts["missing_count"] == 0 else "HOLD_SCHEMA"
            result["target_count"] = counts["target_count"]
            result["missing_count"] = counts["missing_count"]
            result["direct_memberships"] = counts["direct_memberships"]
            result["select_count"] = counts["select_count"]
            result["write_count"] = counts["write_count"]
            result["owned_count"] = counts["owned_count"]
            result["rls_count"] = counts["rls_count"]
            result["force_rls_count"] = counts["force_rls_count"]
            result["policy_count"] = counts["policy_count"]
            overbroad = (
                not flags["session_identity_match"]
                or not flags["role_exists"]
                or any(
                    flags[key]
                    for key in (
                        "is_super", "bypass_rls", "create_role",
                        "create_db_role", "replicate", "database_create",
                        "schema_create",
                    )
                )
                or counts["direct_memberships"] > 0
                or counts["owned_database_count"] > 0
                or counts["owned_schema_count"] > 0
                or counts["owned_count"] > 0
                or counts["write_count"] > 0
            )
            if counts["missing_count"]:
                result["reader"] = "HOLD_SCHEMA"
            elif overbroad:
                result["reader"] = "HOLD_OVERBROAD_READER"
            elif counts["select_count"]:
                result["reader"] = "HOLD_BROAD_BASE_SELECT"
            else:
                result["reader"] = "PASS_CATALOG_ONLY_NO_BASE_SELECT"
            # Catalog flags are never evidence of server-side 910001 isolation.
            return result
    except ProjectionHold as exc:
        result["metadata"] = str(exc)
        return result
    except Exception:  # noqa: BLE001 - never expose DB errors/values.
        result["metadata"] = "HOLD_DATABASE_FAILURE"
        return result
    finally:
        if transaction is not None and getattr(transaction, "is_active", True):
            try:
                transaction.rollback()
            except Exception:  # noqa: BLE001 - fail closed even on cleanup failure.
                result["metadata"] = "HOLD_CLEANUP_FAILURE"
                result["reader"] = "HOLD_UNPROVEN"


# PCR V17 R5H: distinct, INERT-by-default hosted source-only candidate.
# This is NEVER an approval to publish, to use the existing application writer,
# or to perform a protected database read. R5C and R5F remain intact.
R5H_ENABLE_ENV = "XAFPAY_R5H_WND_CATALOG_ENABLED"
R5H_EXPIRES_ENV = "XAFPAY_R5H_WND_CATALOG_EXPIRES_AT"
R5H_APPROVED_SHA_ENV = "XAFPAY_R5H_WND_CATALOG_APPROVED_SOURCE_SHA"
R5H_EVENT_ENV = "XAFPAY_R5H_WND_CATALOG_RELEASE_EVENT"
R5H_INSTANCE_SERVICE_ENV = "XAFPAY_R5H_WND_CATALOG_APPROVED_SERVICE_ID"
R5H_MAX_TTL = timedelta(minutes=10)
R5H_EXPECTED_REGION = "frankfurt"
_R5H_LOCK = threading.Lock()
_R5H_CLAIMED = False
_R5H_LOGGER = logging.getLogger("xbos.p0d_r5h")

# A single constant, typed, bounded identity probe. Only these preapproved
# string parameters, never caller-controlled SQL, relation names or tenant IDs.
_R5H_IDENTITY_SQL = """
/* r5h:identity */
SELECT
  current_database() = :approved_database AS database_ok,
  current_user = :approved_principal AS current_user_ok,
  session_user = :approved_principal AS session_user_ok
"""


def _r5h_gate(environment: Mapping[str, str], now: datetime) -> str:
    if str(environment.get(R5H_ENABLE_ENV, "")).strip() != "1":
        if not environment.get(R5H_ENABLE_ENV):
            return "DISABLED"
        return "HOLD_ENABLE_INVALID"

    expiry = _parse_expiry(environment.get(R5H_EXPIRES_ENV))
    if expiry is None or not now < expiry <= now + R5H_MAX_TTL:
        return "HOLD_EXPIRED_OR_OVERSCOPED"

    expected = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": EXPECTED_RENDER_SERVICE_ID,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": EXPECTED_RENDER_HOST,
        "RENDER_GIT_BRANCH": EXPECTED_RENDER_BRANCH,
        "RENDER_REGION": R5H_EXPECTED_REGION,
    }
    for key, expected_value in expected.items():
        if str(environment.get(key, "")).strip() != expected_value:
            return "HOLD_RUNTIME_ATTESTATION"

    deployed_sha = str(environment.get("RENDER_GIT_COMMIT", "")).strip().lower()
    admitted_sha = str(environment.get(R5H_APPROVED_SHA_ENV, "")).strip().lower()
    if (
        len(deployed_sha) != 40
        or any(char not in "0123456789abcdef" for char in deployed_sha)
        or deployed_sha != admitted_sha
    ):
        return "HOLD_SOURCE_ATTESTATION"

    release_event = str(environment.get(R5H_EVENT_ENV, "")).strip()
    if (
        len(release_event) != 16
        or any(char not in "0123456789abcdefABCDEF" for char in release_event)
    ):
        return "HOLD_RELEASE_EVENT"

    # A process-local guard alone is NOT a distributed execution lease:
    # release custody must independently verify this running instance and
    # permit exactly one startup. No fallback if the identity is unavailable.
    runtime_instance = str(environment.get("HOSTNAME", "")).strip()
    approved_service = str(environment.get(R5H_INSTANCE_SERVICE_ENV, "")).strip()
    if (
        approved_service != EXPECTED_RENDER_SERVICE_ID
        or not runtime_instance.startswith(EXPECTED_RENDER_SERVICE_ID + "-")
        or not 8 <= len(runtime_instance) <= 96
        or any(not (c.isalnum() or c == "-") for c in runtime_instance)
        or os.getpid() <= 0
    ):
        return "HOLD_INSTANCE_ATTESTATION"

    # Explicit rejection of accidental concurrent reactivation of R5C.
    if str(environment.get(ENABLE_ENV, "")).strip() == "1":
        return "HOLD_R5C_CONFLICT"
    return "PASS"


def _r5h_claim_once() -> bool:
    global _R5H_CLAIMED
    with _R5H_LOCK:
        if _R5H_CLAIMED:
            return False
        _R5H_CLAIMED = True
        return True


def _r5h_result(gate: str) -> dict[str, str | int]:
    return {
        "generation": "p0d-r5h-catalog-r0",
        "gate": gate,
        "identity": "NOT_RUN",
        "metadata": "NOT_RUN",
        "reader": "HOLD_UNPROVEN",
        "tenant_isolation": "HOLD_UNPROVEN",
    }


def _r5h_bounded_catalog(row: Mapping[str, Any]) -> dict[str, str | int]:
    """Only approved booleans and 0..100 metadata counts, never source rows."""
    counts: dict[str, int] = {}
    for key in _R5F_COUNTER_KEYS:
        value = row[key]
        if type(value) is not int or not 0 <= value <= 100:
            raise ProjectionHold("HOLD_OUTPUT_BOUNDS")
        counts[key] = value
    flags: dict[str, bool] = {}
    for key in _R5F_BOOLEAN_KEYS:
        if type(row[key]) is not bool:
            raise ProjectionHold("HOLD_OUTPUT_BOUNDS")
        flags[key] = row[key]
    if (
        counts["target_count"] != R5F_EXPECTED_COUNT
        or any(
            counts[key] > R5F_EXPECTED_COUNT
            for key in (
                "missing_count", "owned_count", "select_count",
                "write_count", "rls_count", "force_rls_count",
            )
        )
    ):
        raise ProjectionHold("HOLD_SCHEMA_BOUNDS")
    if counts["missing_count"] > 0:
        return {"metadata": "HOLD_SCHEMA", "reader": "HOLD_UNPROVEN"}

    overbroad = (
        not flags["session_identity_match"]
        or not flags["role_exists"]
        or any(
            flags[key]
            for key in (
                "is_super", "bypass_rls", "create_role", "create_db_role",
                "replicate", "database_create", "schema_create",
            )
        )
        or counts["owned_database_count"] > 0
        or counts["owned_schema_count"] > 0
        or counts["owned_count"] > 0
        or counts["write_count"] > 0
        or counts["direct_memberships"] > 0
    )
    if overbroad:
        reader = "HOLD_OVERBROAD_READER"
    elif counts["select_count"] > 0:
        reader = "HOLD_BROAD_BASE_SELECT"
    else:
        reader = "PASS_CATALOG_ONLY_NO_BASE_SELECT"

    return {
        "metadata": "PASS",
        "reader": reader,
        "target_count": counts["target_count"],
        "missing_count": counts["missing_count"],
        "direct_memberships": counts["direct_memberships"],
        "select_count": counts["select_count"],
        "write_count": counts["write_count"],
        "owned_count": counts["owned_count"],
        "rls_count": counts["rls_count"],
        "force_rls_count": counts["force_rls_count"],
        "policy_count": counts["policy_count"],
    }


def run_r5h_hosted_catalog(
    engine: Any,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, str | int]:
    """Nonpublic metadata ONLY, with independent admission and no tenant reads.

    This is a future source candidate, not authorization to run on Render.
    """
    environment = os.environ if environ is None else environ
    at = (now or _utc_now()).astimezone(timezone.utc)
    result = _r5h_result(_r5h_gate(environment, at))
    if result["gate"] != "PASS":
        return result

    # Claim even if the connection fails: no automatic retry after a
    # partial startup, cancellation or failure.
    if not _r5h_claim_once():
        result["gate"] = "HOLD_ALREADY_EXECUTED"
        return result

    transaction = None
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='2000ms'"))
            connection.execute(text("SET LOCAL lock_timeout='500ms'"))
            connection.execute(
                text("SET LOCAL idle_in_transaction_session_timeout='3000ms'")
            )
            identity = connection.execute(
                text(_R5H_IDENTITY_SQL),
                {
                    "approved_database": EXPECTED_DATABASE,
                    "approved_principal": EXPECTED_DATABASE_USER,
                },
            ).mappings().one()
            if not all(
                type(identity.get(key)) is bool and identity[key]
                for key in ("database_ok", "current_user_ok", "session_user_ok")
            ):
                result["identity"] = "HOLD_DB_IDENTITY"
                return result
            result["identity"] = "PASS"
            catalog = connection.execute(
                text(_R5F_FIXED_CATALOG_SQL)
            ).mappings().one()
            result.update(_r5h_bounded_catalog(catalog))
            return result
    except ProjectionHold as exc:
        result["metadata"] = str(exc)
        return result
    except Exception:  # noqa: BLE001 - no DB errors/secrets in status or logs.
        result["metadata"] = "HOLD_DATABASE_FAILURE"
        return result
    finally:
        if transaction is not None and getattr(transaction, "is_active", True):
            try:
                transaction.rollback()
            except Exception:  # noqa: BLE001 - never hide rollback failure.
                result["metadata"] = "HOLD_CLEANUP_FAILURE"
                result["reader"] = "HOLD_UNPROVEN"


def run_r5h_hosted_startup_diagnostic() -> None:
    """Only registered startup path; off by default, no HTTP route.

    An operator cannot infer CEO admission from these environment controls.
    Effective authorization, exact deployments, instance custody and any
    application-principal exception require separate CEO issuance.
    """
    now = _utc_now()
    environment = os.environ
    gate = _r5h_gate(environment, now)
    if gate != "PASS":
        return
    try:
        from database import engine as application_engine

        result = run_r5h_hosted_catalog(
            application_engine, environ=environment, now=now
        )
    except Exception:  # noqa: BLE001
        result = _r5h_result("PASS")
        result["metadata"] = "HOLD_DATABASE_FAILURE"

    # Never include database identifiers, raw rows, SQL exceptions, DSNs,
    # runtime environment variables, PII, secrets or financial values.
    allowed = ("generation", "gate", "identity", "metadata",
               "reader", "tenant_isolation")
    safe = {key: str(result[key]) for key in allowed}
    _R5H_LOGGER.warning(
        "P0D_R5H_WND_HOSTED_CATALOG %s",
        json.dumps(safe, sort_keys=True, separators=(",", ":")),
    )


def register_r5h_hosted_catalog_diagnostic(app) -> None:
    """Separate startup registration, no tenant route or publication."""
    app.add_event_handler("startup", run_r5h_hosted_startup_diagnostic)
