# core/shared/idempotency.py

from sqlalchemy.orm import Session

class IdempotencyError(Exception):
    pass


def check_idempotency_key(
    db: Session,
    *,
    key: str,
    scope: str,
):
    """
    Ensure an operation is executed only once.

    This is a stub for now.
    Real implementation will persist keys.
    """
    return


def record_idempotency_key(
    db: Session,
    *,
    key: str,
    scope: str,
    reference_id: int,
):
    """
    Record successful execution.
    """
    return
