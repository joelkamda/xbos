"""D1 producer factory must not compose a writable or missing authority."""
from datetime import datetime, timezone
import pytest
from platform_admin.neutral_d1_sql_services import (
    compose_read_only_d1_services, D1ServiceAdmissionDenied
)
from platform_admin.neutral_d1_read_router import NeutralReadServices


class DB:
    def __init__(self, status="on", error=False):
        self.status=status
        self.error=error
        self.seen=[]
    def execute(self, statement):
        self.seen.append(str(statement))
        if self.error:
            raise RuntimeError("db offline")
        class Res:
            def __init__(self, v): self.v=v
            def scalar_one(self): return self.v
        return Res(self.status)


class TenantGateway:
    def tenant_lifecycle(self, tenant_id): return "active"


class ReadinessGateway:
    def assess(self, **kwargs): return {}


def test_all_five_sql_bound_producers_are_real_domain_classes():
    from core.platform.security_authority import SecurityAuthority
    from core.platform.operating_context.service import OperatingContextAuthority
    from core.platform.structure.service import StructuralAuthority
    from pack_platform.service import PackAuthority
    from platform_admin.service import PlatformAdministrationAuthority
    db=DB()
    s=compose_read_only_d1_services(db,tenant_gateway=TenantGateway(),
                                    readiness_gateway=ReadinessGateway(),
                                    clock=lambda: datetime.now(timezone.utc))
    assert isinstance(s,NeutralReadServices)
    assert isinstance(s.pc1,StructuralAuthority)
    assert isinstance(s.pc4,OperatingContextAuthority)
    assert isinstance(s.pc5,SecurityAuthority)
    assert isinstance(s.pa,PlatformAdministrationAuthority)
    assert isinstance(s.pk,PackAuthority)
    assert db.seen==["SHOW transaction_read_only"]


@pytest.mark.parametrize("mode", ["off","0","",None])
def test_writable_or_unproven_transaction_denied(mode):
    with pytest.raises(D1ServiceAdmissionDenied,match="SQL_WRITABLE_TRANSACTION_FORBIDDEN"):
        compose_read_only_d1_services(DB(mode),tenant_gateway=TenantGateway(),
                                      readiness_gateway=ReadinessGateway())


def test_unavailable_database_denied():
    with pytest.raises(D1ServiceAdmissionDenied,match="SQL_READ_ONLY_PROOF_UNAVAILABLE"):
        compose_read_only_d1_services(DB(error=True),tenant_gateway=TenantGateway(),
                                      readiness_gateway=ReadinessGateway())


def test_no_missing_or_synthetic_gateway_defaults():
    for a,b in ((None,ReadinessGateway()),(TenantGateway(),None),
                (object(),ReadinessGateway()),(TenantGateway(),object())):
        with pytest.raises(D1ServiceAdmissionDenied):
            compose_read_only_d1_services(DB(),tenant_gateway=a,readiness_gateway=b)


def test_no_runtime_session_denied():
    with pytest.raises(D1ServiceAdmissionDenied):
        compose_read_only_d1_services(None,tenant_gateway=TenantGateway(),
                                      readiness_gateway=ReadinessGateway())
