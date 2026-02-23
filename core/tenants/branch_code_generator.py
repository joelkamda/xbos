# core/tenants/branch_code_generator.py

from sqlalchemy.orm import Session
from core.tenants.tenant_model import Branch


def generate_branch_code(db: Session, tenant_id: int) -> str:
    """
    Generates sequential branch codes per tenant:

        BR001, BR002, BR003, ...

    For tenant-specific independence.
    """

    prefix = "BR"

    count = (
        db.query(Branch)
        .filter(Branch.tenant_id == tenant_id)
        .count()
    )

    next_number = count + 1

    return f"{prefix}{next_number:03d}"
