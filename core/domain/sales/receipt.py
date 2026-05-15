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

    Safer than COUNT(*) + 1:
    - reads the highest existing receipt serial for the month
    - increments it
    - avoids duplicate receipt numbers when failed/pending attempts exist
    """

    mm = created_at.strftime("%m")
    yy = created_at.strftime("%y")

    tt = str(tenant_id).zfill(2)
    bb = str(branch_id).zfill(2)

    prefix = f"R-{tt}{bb}-{mm}{yy}-"

    seq_query = text("""
        SELECT COALESCE(
            MAX(CAST(RIGHT(receipt_no, 5) AS INTEGER)),
            0
        ) + 1
        FROM sales
        WHERE tenant_id = :tenant_id
          AND branch_id = :branch_id
          AND receipt_no LIKE :prefix
    """)

    result = db.execute(
        seq_query,
        {
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "prefix": f"{prefix}%",
        },
    ).scalar()

    serial = str(result).zfill(5)

    return f"{prefix}{serial}"