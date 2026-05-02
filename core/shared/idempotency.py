# core/shared/idempotency.py

from sqlalchemy.orm import Session
from sqlalchemy import text


class IdempotencyError(Exception):
    pass


def check_idempotency_key(
    db: Session,
    *,
    key: str,
    scope: str,
):
    """
    Return existing record if key already used.
    """
    result = db.execute(
        text("""
            SELECT id, key, scope, reference_id
            FROM idempotency_keys
            WHERE key = :key AND scope = :scope
            LIMIT 1
        """),
        {"key": key, "scope": scope},
    ).mappings().first()

    return result  # None if not found


def record_idempotency_key(
    db: Session,
    *,
    key: str,
    scope: str,
    reference_id: int,
):
    """
    Insert idempotency record.
    Will raise IntegrityError if duplicate (race condition safe).
    """
    db.execute(
        text("""
            INSERT INTO idempotency_keys (key, scope, reference_id)
            VALUES (:key, :scope, :reference_id)
        """),
        {
            "key": key,
            "scope": scope,
            "reference_id": reference_id,
        },
    )