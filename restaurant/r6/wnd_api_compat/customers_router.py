import re
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from core.rbac.utils.permission_decorator import require_permissions

router = APIRouter(tags=["WND R6 Compatibility - Customers"])


def _clean(value: Any) -> str | None:
    result = str(value or "").strip()
    return result or None


def _normalize_phone(value: Any) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    normalized = re.sub(r"[^0-9+]", "", raw)
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]
    if normalized.count("+") > 1 or ("+" in normalized and not normalized.startswith("+")):
        normalized = normalized.replace("+", "")
    return normalized or None


class CustomerCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, max_length=254)
    notes: Optional[str] = None


class CustomerPatchPayload(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, max_length=254)
    notes: Optional[str] = None


def _context(request: Request) -> tuple[int, int, int | None]:
    ctx = request.state.user
    tenant_id = int(ctx["tenant_id"])
    if tenant_id != 2:
        raise HTTPException(status_code=404, detail="Compatibility route not available")
    return tenant_id, int(ctx["branch_id"]), ctx.get("id") or ctx.get("user_id")


def _serialize_customer(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": int(data["id"]),
        "tenant_id": int(data["tenant_id"]),
        "branch_id": int(data["branch_id"]),
        "name": data.get("name"),
        "primary_phone": data.get("primary_phone"),
        "normalized_phone": data.get("normalized_phone"),
        "email": data.get("email"),
        "notes": data.get("notes"),
        "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
        "updated_at": data.get("updated_at").isoformat() if data.get("updated_at") else None,
        "ar_balance": float(data.get("ar_balance") or 0),
        "open_ar_count": int(data.get("open_ar_count") or 0),
        "ar_count": int(data.get("ar_count") or 0),
    }


_CUSTOMER_SELECT = """
SELECT
    c.*,
    COALESCE(SUM(ar.balance_due) FILTER (WHERE ar.status IN ('open','partial')), 0) AS ar_balance,
    COUNT(ar.id) FILTER (WHERE ar.status IN ('open','partial')) AS open_ar_count,
    COUNT(ar.id) AS ar_count
FROM customers c
LEFT JOIN accounts_receivable ar
  ON ar.customer_id = c.id
 AND ar.tenant_id = c.tenant_id
 AND ar.branch_id = c.branch_id
"""


def _customer_for_context(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    customer_id: int,
) -> dict[str, Any]:
    row = db.execute(
        text(
            _CUSTOMER_SELECT
            + " WHERE c.id=:customer_id AND c.tenant_id=:tenant_id AND c.branch_id=:branch_id GROUP BY c.id"
        ),
        {"customer_id": customer_id, "tenant_id": tenant_id, "branch_id": branch_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Customer not found")
    return _serialize_customer(row)


@router.get("")
@require_permissions("customer.view")
def list_customers(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    tenant_id, branch_id, _ = _context(request)
    q_clean = _clean(q)
    params: dict[str, Any] = {"tenant_id": tenant_id, "branch_id": branch_id}
    where = ["c.tenant_id=:tenant_id", "c.branch_id=:branch_id"]
    if q_clean:
        params["q"] = f"%{q_clean}%"
        where.append("(c.name ILIKE :q OR c.primary_phone ILIKE :q OR c.email ILIKE :q)")

    rows = db.execute(
        text(
            _CUSTOMER_SELECT
            + " WHERE " + " AND ".join(where)
            + " GROUP BY c.id ORDER BY lower(c.name), c.id"
        ),
        params,
    ).mappings().all()

    unlinked = db.execute(
        text(
            """
            SELECT
                MIN(ar.id) AS ar_id,
                trim(ar.customer_name) AS customer_name,
                trim(ar.customer_phone) AS customer_phone,
                COUNT(*) AS account_count,
                COALESCE(SUM(ar.balance_due), 0) AS balance_due
            FROM accounts_receivable ar
            WHERE ar.tenant_id=:tenant_id
              AND ar.branch_id=:branch_id
              AND ar.customer_id IS NULL
              AND ar.status IN ('open','partial')
              AND nullif(trim(coalesce(ar.customer_name,'')), '') IS NOT NULL
              AND lower(trim(ar.customer_name)) <> 'debtor not recorded'
            GROUP BY trim(ar.customer_name), trim(ar.customer_phone)
            ORDER BY COALESCE(SUM(ar.balance_due), 0) DESC, trim(ar.customer_name)
            """
        ),
        {"tenant_id": tenant_id, "branch_id": branch_id},
    ).mappings().all()

    return {
        "items": [_serialize_customer(row) for row in rows],
        "unlinked_ar": [
            {
                "ar_id": int(row["ar_id"]),
                "customer_name": row["customer_name"],
                "customer_phone": row["customer_phone"],
                "account_count": int(row["account_count"] or 0),
                "balance_due": float(row["balance_due"] or 0),
            }
            for row in unlinked
        ],
    }


@router.get("/{customer_id}")
@require_permissions("customer.view")
def get_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    tenant_id, branch_id, _ = _context(request)
    return _customer_for_context(
        db, tenant_id=tenant_id, branch_id=branch_id, customer_id=customer_id
    )


@router.get("/{customer_id}/receivables")
@require_permissions("customer.view", "accounting.view")
def get_customer_receivables(customer_id: int, request: Request, db: Session = Depends(get_db)):
    tenant_id, branch_id, _ = _context(request)
    exists = db.execute(
        text("SELECT 1 FROM customers WHERE id=:id AND tenant_id=:tenant_id AND branch_id=:branch_id"),
        {"id": customer_id, "tenant_id": tenant_id, "branch_id": branch_id},
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="Customer not found")

    rows = db.execute(
        text(
            """
            SELECT id, order_id, sale_id, payment_intent_id, customer_name, customer_phone,
                   original_amount, paid_amount, balance_due, status, created_at, updated_at, settled_at
            FROM accounts_receivable
            WHERE tenant_id=:tenant_id AND branch_id=:branch_id AND customer_id=:customer_id
            ORDER BY created_at DESC NULLS LAST, id DESC
            """
        ),
        {"tenant_id": tenant_id, "branch_id": branch_id, "customer_id": customer_id},
    ).mappings().all()

    return {
        "items": [
            {
                **dict(row),
                "original_amount": float(row["original_amount"] or 0),
                "paid_amount": float(row["paid_amount"] or 0),
                "balance_due": float(row["balance_due"] or 0),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "settled_at": row["settled_at"].isoformat() if row["settled_at"] else None,
            }
            for row in rows
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
@require_permissions("customer.create")
def create_customer(request: Request, payload: CustomerCreatePayload = Body(...), db: Session = Depends(get_db)):
    tenant_id, branch_id, user_id = _context(request)
    name = _clean(payload.name)
    phone = _clean(payload.phone)
    normalized_phone = _normalize_phone(phone)
    try:
        row = db.execute(
            text(
                """
                INSERT INTO customers (
                    tenant_id, branch_id, name, primary_phone, normalized_phone,
                    email, notes, created_by_user_id
                )
                VALUES (:tenant_id, :branch_id, :name, :phone, :normalized_phone,
                        :email, :notes, :user_id)
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "name": name,
                "phone": phone,
                "normalized_phone": normalized_phone,
                "email": _clean(payload.email),
                "notes": _clean(payload.notes),
                "user_id": user_id,
            },
        ).mappings().one()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A customer with this phone already exists")
    return _customer_for_context(db, tenant_id=tenant_id, branch_id=branch_id, customer_id=int(row["id"]))


@router.patch("/{customer_id}")
@require_permissions("customer.update")
def update_customer(customer_id: int, request: Request, payload: CustomerPatchPayload = Body(...), db: Session = Depends(get_db)):
    tenant_id, branch_id, _ = _context(request)
    current = db.execute(
        text("SELECT * FROM customers WHERE id=:id AND tenant_id=:tenant_id AND branch_id=:branch_id FOR UPDATE"),
        {"id": customer_id, "tenant_id": tenant_id, "branch_id": branch_id},
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="Customer not found")

    next_name = _clean(payload.name) if payload.name is not None else current["name"]
    next_phone = _clean(payload.phone) if payload.phone is not None else current["primary_phone"]
    try:
        db.execute(
            text(
                """
                UPDATE customers
                SET name=:name,
                    primary_phone=:phone,
                    normalized_phone=:normalized_phone,
                    email=:email,
                    notes=:notes,
                    updated_at=now()
                WHERE id=:id AND tenant_id=:tenant_id AND branch_id=:branch_id
                """
            ),
            {
                "name": next_name,
                "phone": next_phone,
                "normalized_phone": _normalize_phone(next_phone),
                "email": _clean(payload.email) if payload.email is not None else current["email"],
                "notes": _clean(payload.notes) if payload.notes is not None else current["notes"],
                "id": customer_id,
                "tenant_id": tenant_id,
                "branch_id": branch_id,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A customer with this phone already exists")
    return _customer_for_context(db, tenant_id=tenant_id, branch_id=branch_id, customer_id=customer_id)


@router.post("/from-ar/{ar_id}")
@require_permissions("customer.create", "accounting.post")
def create_or_link_from_ar(ar_id: int, request: Request, db: Session = Depends(get_db)):
    tenant_id, branch_id, user_id = _context(request)
    ar = db.execute(
        text(
            """
            SELECT * FROM accounts_receivable
            WHERE id=:ar_id AND tenant_id=:tenant_id AND branch_id=:branch_id
            FOR UPDATE
            """
        ),
        {"ar_id": ar_id, "tenant_id": tenant_id, "branch_id": branch_id},
    ).mappings().first()
    if not ar:
        raise HTTPException(status_code=404, detail="A/R account not found")
    if ar["customer_id"]:
        db.commit()
        return _customer_for_context(db, tenant_id=tenant_id, branch_id=branch_id, customer_id=int(ar["customer_id"]))

    name = _clean(ar["customer_name"])
    if not name or name.lower() == "debtor not recorded":
        db.rollback()
        raise HTTPException(status_code=400, detail="Identify the debtor before creating a customer")

    phone = _clean(ar["customer_phone"])
    normalized_phone = _normalize_phone(phone)
    customer_id = None
    if normalized_phone:
        customer_id = db.execute(
            text(
                """
                SELECT id FROM customers
                WHERE tenant_id=:tenant_id AND branch_id=:branch_id AND normalized_phone=:normalized_phone
                """
            ),
            {"tenant_id": tenant_id, "branch_id": branch_id, "normalized_phone": normalized_phone},
        ).scalar()

    if not customer_id:
        customer_id = db.execute(
            text(
                """
                INSERT INTO customers (
                    tenant_id, branch_id, name, primary_phone, normalized_phone, created_by_user_id
                )
                VALUES (:tenant_id, :branch_id, :name, :phone, :normalized_phone, :user_id)
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "name": name,
                "phone": phone,
                "normalized_phone": normalized_phone,
                "user_id": user_id,
            },
        ).scalar_one()

    # Link every exact explicit identity in this context, never name-only guessing.
    if normalized_phone:
        db.execute(
            text(
                """
                UPDATE accounts_receivable
                SET customer_id=:customer_id, updated_at=updated_at
                WHERE tenant_id=:tenant_id AND branch_id=:branch_id AND customer_id IS NULL
                  AND regexp_replace(coalesce(customer_phone,''), '[^0-9+]', '', 'g')=:normalized_phone
                """
            ),
            {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "normalized_phone": normalized_phone,
            },
        )
    else:
        db.execute(
            text("UPDATE accounts_receivable SET customer_id=:customer_id WHERE id=:ar_id"),
            {"customer_id": customer_id, "ar_id": ar_id},
        )

    db.commit()
    return _customer_for_context(db, tenant_id=tenant_id, branch_id=branch_id, customer_id=int(customer_id))
