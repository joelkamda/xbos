"""Portable deployment selector, never a source of new entitlement authority."""
from dataclasses import dataclass
from enum import Enum

class DeploymentProfile(str, Enum):
    CLOUD = "cloud"
    LOCAL_SERVER = "local_server"

@dataclass(frozen=True)
class NodeScope:
    profile: DeploymentProfile
    tenant_id: int
    node_id: str
    branch_id: int

    def __post_init__(self):
        if not isinstance(self.profile, DeploymentProfile):
            raise ValueError("UNRECOGNIZED_DEPLOYMENT_PROFILE")
        if self.tenant_id <= 0 or self.branch_id <= 0 or not self.node_id.strip():
            raise ValueError("INVALID_NODE_SCOPE")
