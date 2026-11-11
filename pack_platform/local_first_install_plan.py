"""Installation plan is nonoperative until signed installer/recovery admitted."""
from dataclasses import dataclass
from pack_platform.local_first_bundle_verifier import require_pack

@dataclass(frozen=True)
class LocalPackInstallPlan:
    tenant_id: int
    pack_code: str
    version: int
    dry_run_only: bool=True

def plan_pack_install(envelope, **kwargs):
    verified=require_pack(envelope,**kwargs)
    return LocalPackInstallPlan(verified.tenant_id,verified.pack_code,verified.version)
