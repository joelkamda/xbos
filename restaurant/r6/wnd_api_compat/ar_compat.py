from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

BUSINESS_TZ = ZoneInfo("Africa/Douala")
UTC_TZ = timezone.utc


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC_TZ)
        return value.astimezone(UTC_TZ).isoformat()
    return str(value)


def _ctx(request: Request) -> tuple[int, int]:
    ctx = getattr(request.state, "user", None)
    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(status_code=401, detail="Missing auth context")
    tenant_id = int(ctx["tenant_id"])
    if tenant_id != 2:
        raise HTTPException(status_code=404, detail="Compatibility route not available")
    return tenant_id, int(ctx["branch_id"])


def _serialize_account(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": int(data["id"]),
        "tenant_id": int(data["tenant_id"]),
        "branch_id": int(data["branch_id"]),
        "order_id": data.get("order_id"),
        "sale_id": data.get("sale_id"),
        "payment_intent_id": data.get("payment_intent_id"),
        "customer_id": data.get("customer_id"),
        "customer_name": data.get("customer_name"),
        "customer_phone": data.get("customer_phone"),
        "note": data.get("note"),
        "original_amount": _f(data.get("original_amount")),
        "paid_amount": _f(data.get("paid_amount")),
        "balance_due": _f(data.get("balance_due")),
        "status": data.get("status") or "open",
        "created_by_user_id": data.get("created_by_user_id"),
        "created_at": _iso(data.get("created_at")),
        "updated_at": _iso(data.get("updated_at")),
        "settled_at": _iso(data.get("settled_at")),
    }


def _serialize_repayment(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": int(data["id"]),
        "tenant_id": int(data["tenant_id"]),
        "branch_id": int(data["branch_id"]),
        "ar_id": int(data["ar_id"]),
        "amount": _f(data.get("amount")),
        "payment_method": data.get("payment_method") or "cash",
        "reference": data.get("reference"),
        "note": data.get("note"),
        "created_by_user_id": data.get("created_by_user_id"),
        "created_at": _iso(data.get("created_at")),
    }


def _account_detail(db: Session, *, tenant_id: int, branch_id: int, ar_id: int, for_update: bool = False):
    suffix = " FOR UPDATE" if for_update else ""
    row = db.execute(text(
        "SELECT * FROM accounts_receivable WHERE id=:id AND tenant_id=:t AND branch_id=:b" + suffix
    ), {"id": ar_id, "t": tenant_id, "b": branch_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="A/R account not found")
    result = _serialize_account(row)
    repayments = db.execute(text("""
        SELECT * FROM accounts_receivable_repayments
        WHERE tenant_id=:t AND branch_id=:b AND ar_id=:id
        ORDER BY created_at DESC, id DESC
    """), {"t": tenant_id, "b": branch_id, "id": ar_id}).mappings().all()
    result["repayments"] = [_serialize_repayment(r) for r in repayments]
    return result


def get_account(ar_id: int, request: Request, db: Session):
    tenant_id, branch_id = _ctx(request)
    return _account_detail(db, tenant_id=tenant_id, branch_id=branch_id, ar_id=ar_id)


def _parse_date(value: Optional[str], *, inclusive_end: bool = False):
    if not value:
        return None
    raw = str(value).strip()
    try:
        if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
            local = datetime.fromisoformat(raw).replace(tzinfo=BUSINESS_TZ)
            if inclusive_end:
                local += timedelta(days=1)
            return local.astimezone(UTC_TZ).replace(tzinfo=None)
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BUSINESS_TZ)
        return parsed.astimezone(UTC_TZ).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid A/R date filter") from exc


def list_accounts(*, request: Request, db: Session, limit: int = 25, offset: int = 0,
                  status_filter: str = "active", start: str | None = None,
                  end: str | None = None, q: str | None = None):
    tenant_id, branch_id = _ctx(request)
    safe_limit = min(max(int(limit or 25), 1), 200)
    safe_offset = max(int(offset or 0), 0)
    safe_status = str(status_filter or "active").strip().lower()
    if safe_status not in {"active", "open", "partial", "settled", "cancelled", "all"}:
        raise HTTPException(status_code=400, detail="Invalid A/R status filter")
    start_at = _parse_date(start)
    end_at = _parse_date(end, inclusive_end=True)
    if start_at and end_at and start_at >= end_at:
        raise HTTPException(status_code=400, detail="A/R start date must be before end date")

    where = ["tenant_id=:t", "branch_id=:b"]
    params: dict[str, Any] = {"t": tenant_id, "b": branch_id}
    if safe_status == "active":
        where.append("status IN ('open','partial')")
    elif safe_status != "all":
        where.append("status=:status")
        params["status"] = safe_status
    if start_at is not None:
        where.append("created_at >= :start_at"); params["start_at"] = start_at
    if end_at is not None:
        where.append("created_at < :end_at"); params["end_at"] = end_at
    query = str(q or '').strip()
    if query:
        where.append("""(
            customer_name ILIKE :q OR customer_phone ILIKE :q OR note ILIKE :q OR
            CAST(id AS TEXT) ILIKE :q OR CAST(sale_id AS TEXT) ILIKE :q OR
            CAST(order_id AS TEXT) ILIKE :q OR CAST(payment_intent_id AS TEXT) ILIKE :q
        )""")
        params["q"] = f"%{query}%"
    clause = " AND ".join(where)

    total = int(db.execute(text(f"SELECT COUNT(*) FROM accounts_receivable WHERE {clause}"), params).scalar() or 0)
    page_params = dict(params, limit=safe_limit, offset=safe_offset)
    rows = db.execute(text(f"""
        SELECT * FROM accounts_receivable
        WHERE {clause}
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT :limit OFFSET :offset
    """), page_params).mappings().all()
    items = [_serialize_account(r) for r in rows]

    summary = db.execute(text(f"""
        SELECT COUNT(*) AS account_count,
               COUNT(*) FILTER (WHERE status='open') AS open_count,
               COUNT(*) FILTER (WHERE status='partial') AS partial_count,
               COUNT(*) FILTER (WHERE status='settled') AS settled_count,
               COALESCE(SUM(original_amount),0) AS total_original,
               COALESCE(SUM(paid_amount),0) AS total_paid,
               COALESCE(SUM(balance_due),0) AS total_balance_due
        FROM accounts_receivable WHERE {clause}
    """), params).mappings().one()

    return {
        "limit": safe_limit, "offset": safe_offset, "count": total,
        "page_count": len(items), "status_filter": safe_status,
        "start": start, "end": end, "q": query,
        "summary": {
            "account_count": int(summary["account_count"] or 0),
            "open_count": int(summary["open_count"] or 0),
            "partial_count": int(summary["partial_count"] or 0),
            "settled_count": int(summary["settled_count"] or 0),
            "total_original": _f(summary["total_original"]),
            "total_paid": _f(summary["total_paid"]),
            "total_balance_due": _f(summary["total_balance_due"]),
        },
        "items": items,
    }


def search_accounts(*, request: Request, db: Session, q: str = "", limit: int = 25):
    safe_limit = max(1, min(int(limit or 25), 100))
    raw_query = str(q or "").strip().lower()
    if not raw_query:
        page = list_accounts(request=request, db=db, limit=safe_limit, offset=0)
        return {"query": "", "count": len(page["items"]), "items": page["items"]}
    query = raw_query
    for prefix in ("sale #", "sale ", "bill #", "bill ", "a/r #", "ar #", "a/r ", "ar "):
        if query.startswith(prefix):
            query = query[len(prefix):].strip(); break
    query = query.lstrip('#').strip() or raw_query
    # Fetch active A/R in bounded pages, then preserve the accepted Track-A ranking law.
    ranked = []; offset = 0; seq = 0
    def txt(v): return str(v or '').strip().lower()
    def score(item):
        ar_id, sale_id = txt(item.get('id')), txt(item.get('sale_id'))
        if sale_id == query: return 1000
        if ar_id == query: return 950
        phones = [item.get('customer_phone')]
        names = [item.get('customer_name')]
        refs = [item.get('payment_intent_id'), item.get('note')]
        if any(query == txt(v) for v in phones if v is not None): return 900
        if any(query in txt(v) for v in phones if v is not None): return 850
        if any(query == txt(v) for v in refs if v is not None): return 800
        if any(query in txt(v) for v in names if v is not None): return 700
        if any(query in txt(v) for v in refs if v is not None): return 650
        if any(query in v for v in (ar_id, sale_id) if v): return 500
        return 0
    while True:
        page = list_accounts(request=request, db=db, limit=200, offset=offset)
        items = page['items']
        for item in items:
            rank = score(item)
            if rank: ranked.append((rank, seq, item))
            seq += 1
        if len(items) < 200: break
        offset += 200
    ranked.sort(key=lambda x: (-x[0], x[1]))
    items = [x[2] for x in ranked[:safe_limit]]
    return {"query": raw_query, "count": len(items), "items": items}


def update_identity(*, ar_id: int, customer_name: str, customer_phone: str | None,
                    customer_id: int | None, request: Request, db: Session):
    tenant_id, branch_id = _ctx(request)
    row = db.execute(text("""
        SELECT * FROM accounts_receivable
        WHERE id=:id AND tenant_id=:t AND branch_id=:b FOR UPDATE
    """), {"id": ar_id, "t": tenant_id, "b": branch_id}).mappings().first()
    if not row:
        db.rollback(); raise HTTPException(status_code=404, detail="A/R account not found")
    name = str(customer_name or '').strip()
    phone = str(customer_phone or '').strip() or None
    resolved_customer_id = customer_id
    if customer_id is not None:
        customer = db.execute(text("""
            SELECT id, name, primary_phone FROM customers
            WHERE id=:id AND tenant_id=:t AND branch_id=:b
        """), {"id": int(customer_id), "t": tenant_id, "b": branch_id}).mappings().first()
        if not customer:
            db.rollback(); raise HTTPException(status_code=400, detail="Customer not found in this branch")
        name = str(customer['name'] or '').strip()
        phone = str(customer['primary_phone'] or '').strip() or None
        resolved_customer_id = int(customer['id'])
    if not name:
        db.rollback(); raise HTTPException(status_code=400, detail="Debtor name is required")
    db.execute(text("""
        UPDATE accounts_receivable
        SET customer_id=:customer_id, customer_name=:name, customer_phone=:phone, updated_at=:updated_at
        WHERE id=:id AND tenant_id=:t AND branch_id=:b
    """), {
        "customer_id": resolved_customer_id, "name": name, "phone": phone,
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "id": ar_id, "t": tenant_id, "b": branch_id,
    })
    db.commit()
    return {"ok": True, "account": _account_detail(db, tenant_id=tenant_id, branch_id=branch_id, ar_id=ar_id)}
