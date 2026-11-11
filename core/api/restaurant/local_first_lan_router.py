"""Prospective W LAN boundary; unmounted and not a PC5 authority."""
from dataclasses import dataclass
class LANAccessDenied(PermissionError): pass
@dataclass(frozen=True)
class ServerIssuedScope:
    tenant_id:int
    branch_id:int
    actor:str
    node_id:str
    pc5_verified:bool
    member_active:bool
    revoked:bool
    tls_verified:bool
    action:str

def admit_lan(scope:ServerIssuedScope,*,tenant:int,branch:int,action:str):
    if not isinstance(scope,ServerIssuedScope) or not all((
        scope.pc5_verified,scope.member_active,not scope.revoked,
        scope.tls_verified,scope.tenant_id==tenant,
        scope.branch_id==branch,scope.action==action,
        scope.actor,scope.node_id)):
        raise LANAccessDenied("LOCAL_PC5_TENANT_OR_TLS_DENIED")
    return scope
