"""D1 read-authority composition, not a hosted dependency.

These domain services include writer methods: runtime must give them a
database role with SELECT-only grants, and an enforced read-only transaction.
No PA gateway is synthesized from caller claims or synthetic test readiness.
"""
from __future__ import annotations

from typing import Callable
from datetime import datetime, timezone
from sqlalchemy import text
from core.platform.security_authority import SecurityAuthority
from core.platform.security_authority.sql_repository import SQLSecurityRepository
from core.platform.operating_context.service import OperatingContextAuthority
from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
from core.platform.structure.service import StructuralAuthority
from core.platform.structure.sql_repository import SQLStructuralRepository
from pack_platform.service import PackAuthority
from pack_platform.sql_repository import SQLPackRepository
from platform_admin.service import PlatformAdministrationAuthority
from platform_admin.sql_repository import SQLPlatformAdministrationRepository
from platform_admin.neutral_d1_read_router import NeutralReadServices

READ_ONLY_PROOF_SQL = text("SHOW transaction_read_only")


class D1ServiceAdmissionDenied(RuntimeError):
    pass


def compose_read_only_d1_services(
    db, *, tenant_gateway, readiness_gateway,
    clock: Callable[[], datetime] | None = None,
) -> NeutralReadServices:
    """No fake producer fallback and no implicit DB connection.

    An admitted caller must open a SELECT-only role AND read-only PostgreSQL
    transaction before invoking this factory. It must also validate real PC5
    mapping, tenant scope and certified pack entitlements at request time.
    """
    if db is None or tenant_gateway is None or readiness_gateway is None:
        raise D1ServiceAdmissionDenied("SQL_AND_TRUSTED_GATEWAYS_REQUIRED")
    if not callable(getattr(tenant_gateway, "tenant_lifecycle", None)):
        raise D1ServiceAdmissionDenied("TRUSTED_PC1_TENANT_GATEWAY_REQUIRED")
    if not callable(getattr(readiness_gateway, "assess", None)):
        raise D1ServiceAdmissionDenied("TRUSTED_READINESS_GATEWAY_REQUIRED")
    try:
        transaction_mode = db.execute(READ_ONLY_PROOF_SQL).scalar_one()
    except Exception as exc:
        raise D1ServiceAdmissionDenied("SQL_READ_ONLY_PROOF_UNAVAILABLE") from exc
    if str(transaction_mode).strip().lower() != "on":
        raise D1ServiceAdmissionDenied("SQL_WRITABLE_TRANSACTION_FORBIDDEN")
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    return NeutralReadServices(
        pc5=SecurityAuthority(SQLSecurityRepository(db)),
        pc4=OperatingContextAuthority(SQLOperatingContextRepository(db)),
        pc1=StructuralAuthority(SQLStructuralRepository(db)),
        pa=PlatformAdministrationAuthority(
            SQLPlatformAdministrationRepository(db),
            tenant_gateway=tenant_gateway, readiness_gateway=readiness_gateway
        ),
        pk=PackAuthority(SQLPackRepository(db)),
        clock=clock,
    )


def qualify_local_or_cloud_readonly_connection(
    db, *, profile: str, tenant_id: int,
    verified_server_node: str, trusted_node_profile_reader,
) -> None:
    """Admission check only: neither opens nor writes a DB connection.

    A local node must already have independently verified PC5/session and
    a signed admitted authority epoch. Profile is read from the trusted
    server registry, never from a browser header or arbitrary URL.
    """
    if profile not in ("cloud", "local_server") or type(tenant_id) is not int or tenant_id <= 0:
        raise D1ServiceAdmissionDenied("DEPLOYMENT_PROFILE_OR_TENANT_DENIED")
    if not isinstance(verified_server_node, str) or not verified_server_node.strip():
        raise D1ServiceAdmissionDenied("VERIFIED_NODE_REQUIRED")
    if not callable(trusted_node_profile_reader):
        raise D1ServiceAdmissionDenied("TRUSTED_NODE_PROFILE_READER_REQUIRED")
    try:
        actual = trusted_node_profile_reader(tenant_id, verified_server_node)
        if actual != profile:
            raise D1ServiceAdmissionDenied("NODE_DEPLOYMENT_PROFILE_MISMATCH")
        transaction_mode = db.execute(READ_ONLY_PROOF_SQL).scalar_one()
    except D1ServiceAdmissionDenied:
        raise
    except Exception as exc:
        raise D1ServiceAdmissionDenied("TRUSTED_NODE_OR_SQL_READBACK_UNAVAILABLE") from exc
    if str(transaction_mode).strip().lower() != "on":
        raise D1ServiceAdmissionDenied("WRITABLE_D1_READ_TRANSACTION_FORBIDDEN")
