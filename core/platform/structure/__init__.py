"""PC1 canonical tenant and structural-context authority."""

from .contracts import (
    LegalEntity,
    Location,
    LocationKind,
    OrganizationUnit,
    ProvisionTenant,
    StructuralContext,
    Tenant,
    TenantLifecycle,
)
from .service import StructuralAuthority, StructuralAuthorityError

# Imported lazily by callers that have the repository's production dependencies.
try:
    from .sql_repository import SQLStructuralRepository
except ModuleNotFoundError:  # static/archive verification has no production dependency authority
    SQLStructuralRepository = None  # type: ignore[assignment]

__all__ = [
    "LegalEntity", "Location", "LocationKind", "OrganizationUnit", "ProvisionTenant", "StructuralAuthority",
    "SQLStructuralRepository", "StructuralAuthorityError", "StructuralContext", "Tenant", "TenantLifecycle",
]
