# core/api/tenant_controller.py

from fastapi import APIRouter, HTTPException
from core.tenants.tenant_service import TenantService
from core.tenants.schemas import (
    TenantCreate,
    TenantUpdate,
    BranchCreate,
    BranchUpdate,
)

router = APIRouter(tags=["Tenants"])
service = TenantService()


# ======================================================
# TENANT ROUTES
# ======================================================

@router.post("/")
def create_tenant(payload: TenantCreate):
    """Create tenant + default branch."""
    try:
        return service.create_tenant(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
def list_tenants():
    """List all tenants."""
    return service.list_tenants()


@router.get("/{tenant_id}")
def get_tenant(tenant_id: int):
    """Retrieve a tenant by ID."""
    return service.get_tenant(tenant_id)


@router.put("/{tenant_id}")
def update_tenant(tenant_id: int, payload: TenantUpdate):
    """Update a tenant."""
    try:
        return service.update_tenant(tenant_id, payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tenant_id}")
def delete_tenant(tenant_id: int):
    """Delete a tenant."""
    try:
        service.delete_tenant(tenant_id)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ======================================================
# BRANCH ROUTES
# ======================================================

@router.post("/branch")
def create_branch(payload: BranchCreate):
    """Create a branch for a tenant."""
    try:
        return service.create_branch(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{tenant_id}/branches")
def list_branches(tenant_id: int):
    """List branches for tenant."""
    return service.get_branches(tenant_id)


@router.get("/branch/{branch_id}")
def get_branch(branch_id: int):
    """Retrieve branch by ID."""
    return service.get_branch(branch_id)


@router.put("/branch/{branch_id}")
def update_branch(branch_id: int, payload: BranchUpdate):
    """Update branch details."""
    try:
        return service.update_branch(branch_id, payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/branch/{branch_id}")
def delete_branch(branch_id: int):
    """Delete branch."""
    try:
        service.delete_branch(branch_id)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
