# core/tenants/tenant_id_generator.py

from sqlalchemy.orm import Session
from core.tenants.tenant_model import Tenant


def generate_tenant_code(db: Session, country_prefix: str) -> str:
    """
    Generates codes like:
    CM001, CM002, NG001, US001...

    Pattern:
        prefix + sequential number based on count.
    """

    prefix = country_prefix.upper()

    # Count existing tenants beginning with prefix
    count = (
        db.query(Tenant)
        .filter(Tenant.code.like(f"{prefix}%"))
        .count()
    )

    next_number = count + 1  # sequential

    return f"{prefix}{next_number:03d}"
