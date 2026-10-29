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
