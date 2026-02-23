from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text


def generate_receipt_no(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    created_at: datetime,
) -> str:
    """
    Generate receipt number:
    R-{TT}{BB}-{MM}{YY}-{XXXXX}

    Sequence is branch-scoped and resets monthly.
    """

    mm = created_at.strftime("%m")
    yy = created_at.strftime("%y")

    tt = str(tenant_id).zfill(2)
    bb = str(branch_id).zfill(2)

    # Get next monthly sequence for branch
    seq_query = text("""
        SELECT COUNT(*) + 1
        FROM sales
        WHERE tenant_id = :tenant_id
          AND branch_id = :branch_id
          AND EXTRACT(MONTH FROM created_at) = :month
          AND EXTRACT(YEAR FROM created_at) = :year
    """)

    result = db.execute(
        seq_query,
        {
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "month": int(mm),
            "year": int("20" + yy),
        },
    ).scalar()

    serial = str(result).zfill(5)

    return f"R-{tt}{bb}-{mm}{yy}-{serial}"
