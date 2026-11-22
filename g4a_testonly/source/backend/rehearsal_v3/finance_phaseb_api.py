"""WND V3 detached Finance TEST operator endpoints (NOT real WND or PC5).

Requires explicit test-only import of phaseb_app; original V3 app untouched.
Writes can only create isolated TEST DRAFT records in the N-approved 910001/1
nonpersonal database, after separate schema qualification. Never posts a real
ledger, closes a real period, creates money, issues a PC5 role or calls a PSP.
Auth uses existing limited local TEST session, which is NOT genuine PC5.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from .api import auth
from .seed import connect

TENANT, BRANCH = 920002, 1
GRADE = "HISTORICAL_WND_CATALOG_PLUS_SYNTHETIC_FINANCE_DRAFTS_NOT_PC5"
DOUALA = ZoneInfo("Africa/Douala")
CHANNELS = {"CASH", "MTN", "ORANGE", "BANK"}
FINANCE_KINDS = {"INCOME_TEST", "EXPENSE_TEST", "MOVEMENT_TEST"}
router = APIRouter(prefix="/api/v3/finance-b", tags=["detached-test-finance"])
finance_connect = connect


def deny(status: int, code: str):
    raise HTTPException(status_code=status, detail=code)


def scope(tenant_id: int = TENANT, branch_id: int = BRANCH):
    if type(tenant_id) is not int or type(branch_id) is not int or (tenant_id, branch_id) != (TENANT, BRANCH):
        deny(403, "TEST_TENANT_BRANCH_DENIED")
    return TENANT, BRANCH


def secure_ref(v: str):
    if re.fullmatch(r"[A-Za-z0-9._:-]{8,100}", v) is None:
        deny(422, "TEST_REFERENCE_INVALID")
    return v


def safe_time(v: datetime):
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
        deny(422, "AWARE_TIMESTAMP_REQUIRED")
    return v


def shift_for(value: datetime) -> tuple[date, str]:
    local = safe_time(value).astimezone(DOUALA)
    d = local.date()
    if local.hour < 8:
        return d - timedelta(days=1), "NIGHT"
    return d, "DAY" if local.hour < 18 else "NIGHT"


def shift_bounds(day: date, shift: str):
    if shift not in {"DAY", "NIGHT"}:
        deny(422, "TEST_SHIFT_INVALID")
    start = datetime.combine(day, time(8 if shift == "DAY" else 18), DOUALA)
    end = datetime.combine(day, time(18), DOUALA) if shift == "DAY" else datetime.combine(day + timedelta(days=1), time(8), DOUALA)
    return start, end


def month_bounds(period: str):
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        deny(422, "TEST_MONTH_INVALID")
    try:
        year, month = map(int, period.split("-"))
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
    except ValueError:
        deny(422, "TEST_MONTH_INVALID")
    return (datetime.combine(start, time(8), DOUALA),
            datetime.combine(end, time(8), DOUALA))


def meta():
    return {"grade": GRADE, "tenant": TENANT, "branch": BRANCH,
            "realWndData": False, "realPC5": False, "g3Admitted": False,
            "canApprove": False, "canClose": False, "financePosted": False,
            "customerPaid": False, "externalEffects": False}


class ManualDraft(BaseModel):
    tenant_id: int = Field(default=TENANT, strict=True)
    branch_id: int = Field(default=BRANCH, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: str
    channel: str
    amount_xaf: int = Field(strict=True, ge=1, le=5_000_000)
    effective_at: datetime
    note: str = Field(min_length=4, max_length=250)

    @field_validator("effective_at")
    @classmethod
    def aware_datetime(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AWARE_TIMESTAMP_REQUIRED")
        return value


class TransferDraft(BaseModel):
    tenant_id: int = Field(default=TENANT, strict=True)
    branch_id: int = Field(default=BRANCH, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    from_channel: str
    to_channel: str
    amount_xaf: int = Field(strict=True, ge=1, le=5_000_000)
    effective_at: datetime
    note: str = Field(min_length=4, max_length=250)

    @field_validator("effective_at")
    @classmethod
    def aware_datetime(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AWARE_TIMESTAMP_REQUIRED")
        return value


class ReconDraft(BaseModel):
    tenant_id: int = Field(default=TENANT, strict=True)
    branch_id: int = Field(default=BRANCH, strict=True)
    business_date: date
    shift: str
    cashier_count_xaf: int = Field(strict=True, ge=0, le=100_000_000)


class AliasDraft(BaseModel):
    tenant_id: int = Field(default=TENANT, strict=True)
    branch_id: int = Field(default=BRANCH, strict=True)
    source_debtor_ref: str = Field(min_length=4, max_length=100)
    alias: str = Field(min_length=2, max_length=100)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _scope_body(obj):
    if (obj.tenant_id, obj.branch_id) != (TENANT, BRANCH):
        deny(403, "TEST_TENANT_BRANCH_DENIED")


@router.get("/readiness")
def finance_readiness(actor=Depends(auth)):
    return {**meta(), "status": "LIMITED_TEST_AUTH_ONLY",
            "actor": actor["username"],
            "functions": ["manualDraft", "pairedTransferDraft", "receivablesRead",
                          "aliasReviewDraft", "reconciliationDraft",
                          "monthlyPreview", "reportRead"],
            "genuineReviewer": False}


@router.post("/manual")
def create_manual(body: ManualDraft, actor=Depends(auth)):
    _scope_body(body)
    if body.kind not in {"INCOME_TEST", "EXPENSE_TEST"}:
        deny(422, "TEST_MANUAL_KIND_INVALID")
    if body.channel not in CHANNELS:
        deny(422, "TEST_CHANNEL_INVALID")
    secure_ref(body.idempotency_key)
    signed = body.amount_xaf if body.kind == "INCOME_TEST" else -body.amount_xaf
    business_day, shift = shift_for(body.effective_at)
    # Strictly draft-only, no actual Finance posting.
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("SELECT id::text FROM v3r_b_finance_drafts WHERE idempotency_key=%s",
                      (body.idempotency_key,))
            if c.fetchone():
                deny(409, "TEST_IDEMPOTENCY_DUPLICATE_NO_NEW_EFFECT")
            ident = uuid4()
            c.execute("""INSERT INTO v3r_b_finance_drafts
                (id,tenant_id,branch_id,idempotency_key,kind,channel,
                 signed_amount_xaf,effective_at,note,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ident,TENANT,BRANCH,body.idempotency_key,body.kind,
                 body.channel,signed,body.effective_at,body.note.strip(),actor["username"]))
    return {**meta(), "draftSaved": True, "ref": str(ident),
            "sourceKind": body.kind, "signedAmountXaf": signed,
            "businessDate": business_day.isoformat(), "shift": shift,
            "status": "DRAFT_TEST_NOT_POSTED"}


@router.post("/transfer")
def create_transfer(body: TransferDraft, actor=Depends(auth)):
    _scope_body(body)
    if (body.from_channel not in CHANNELS or body.to_channel not in CHANNELS
            or body.from_channel == body.to_channel):
        deny(422, "TEST_TRANSFER_CHANNELS_INVALID")
    secure_ref(body.idempotency_key)
    business_day, shift = shift_for(body.effective_at)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id FROM v3r_b_finance_drafts
                         WHERE idempotency_key IN (%s,%s)""",
                      (body.idempotency_key + ":out", body.idempotency_key + ":in"))
            if c.fetchone():
                deny(409, "TEST_TRANSFER_DUPLICATE_NO_NEW_EFFECT")
            refs = []
            for direction, channel, signed in (
                ("out",body.from_channel,-body.amount_xaf),
                ("in",body.to_channel,body.amount_xaf),
            ):
                ident = uuid4()
                c.execute("""INSERT INTO v3r_b_finance_drafts
                    (id,tenant_id,branch_id,idempotency_key,kind,channel,
                    signed_amount_xaf,transfer_ref,effective_at,note,created_by)
                    VALUES (%s,%s,%s,%s,'MOVEMENT_TEST',%s,%s,%s,%s,%s,%s)""",
                    (ident,TENANT,BRANCH,body.idempotency_key+":"+direction,
                     channel,signed,body.idempotency_key,body.effective_at,
                     body.note.strip(),actor["username"]))
                refs.append(str(ident))
    return {**meta(),"draftSaved":True,"refs":refs,"businessDate":business_day.isoformat(),
            "shift":shift,"signedTransferNetXaf":0,
            "status":"PAIRED_TRANSFER_DRAFT_NOT_REVENUE"}


@router.get("/entries")
def entries(as_of: datetime = Query(...), tenant_id: int = TENANT,
            branch_id: int = BRANCH, limit: int = Query(100, ge=1, le=200),
            actor=Depends(auth)):
    scope(tenant_id, branch_id)
    safe_time(as_of)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id::text AS ref,kind,channel,signed_amount_xaf,
                         effective_at,created_at,transfer_ref,status,created_by
                         FROM v3r_b_finance_drafts
                         WHERE tenant_id=%s AND branch_id=%s AND effective_at<=%s
                         ORDER BY effective_at,id LIMIT %s""",
                      (TENANT,BRANCH,as_of,limit))
            rows = c.fetchall()
            c.execute("""SELECT f.id::text AS ref,f.order_id::text AS order_ref,
                         f.kind,f.amount_xaf,f.created_at
                         FROM v3r_finance_events f JOIN v3r_orders o ON o.id=f.order_id
                         WHERE o.tenant_id=%s AND o.branch_id=%s AND f.created_at<=%s
                         ORDER BY f.created_at,f.id LIMIT %s""",
                      (TENANT,BRANCH,as_of,limit))
            system_rows=c.fetchall()
    return {**meta(),"asOf":as_of.isoformat(),"rows":rows,
            "draftSource":"manual","systemRows":system_rows,
            "systemSource":"system","systemPaidVerified":False,
            "snapshotPinned":False,"status":"TEST_DRAFT_ROWS_NOT_LEDGER"}


@router.get("/receivables")
def receivables(as_of: datetime = Query(...),tenant_id: int = TENANT,
                branch_id: int = BRANCH, actor=Depends(auth)):
    scope(tenant_id,branch_id)
    safe_time(as_of)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id::text AS ref,amount_xaf,status,created_at
                         FROM v3r_orders
                         WHERE tenant_id=%s AND branch_id=%s AND created_at<=%s
                         ORDER BY created_at,id LIMIT 500""",
                      (TENANT,BRANCH,as_of))
            rows=c.fetchall()
            c.execute("""SELECT id::text AS ref,source_debtor_ref,alias,
                         status,source_sha256
                         FROM v3r_b_debtor_alias_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                         ORDER BY created_at,id LIMIT 500""",
                      (TENANT,BRANCH))
            aliases=c.fetchall()
    total=sum(int(x["amount_xaf"]) for x in rows if x["status"]=="UNPAID_TEST")
    return {**meta(),"asOf":as_of.isoformat(),"rows":[{
        **row,"outstandingXaf":int(row["amount_xaf"]) if row["status"]=="UNPAID_TEST" else 0,
        "debtor":"UNKNOWN_TEST_DEBTOR", "dueDate":None,
        "overdueDays":None,"customerPaid":False
    } for row in rows], "totalUnpaidXaf":total,
        "aliasDrafts":aliases,"status":"TEST_AR_NO_ACTUAL_CUSTOMER_LINK"}


@router.post("/receivables/alias-draft")
def alias_draft(body:AliasDraft,actor=Depends(auth)):
    _scope_body(body)
    with finance_connect() as conn:
        with conn.cursor() as c:
            ident=uuid4()
            c.execute("""INSERT INTO v3r_b_debtor_alias_drafts
                (id,tenant_id,branch_id,source_debtor_ref,alias,
                 source_sha256,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (ident,TENANT,BRANCH,body.source_debtor_ref,body.alias.strip(),
                 body.source_sha256,actor["username"]))
    return {**meta(),"draftSaved":True,"ref":str(ident),
            "status":"REVIEW_REQUIRED_TEST_NO_DEBTOR_MERGE"}


def _cash_in_window(c, start, end):
    c.execute("""SELECT COALESCE(SUM(f.amount_xaf),0) AS amount
                 FROM v3r_finance_events f
                 JOIN v3r_orders o ON o.id=f.order_id
                 WHERE o.tenant_id=%s AND o.branch_id=%s
                   AND f.kind='CASH_RECEIPT_TEST'
                   AND f.created_at >= %s AND f.created_at < %s""",
              (TENANT,BRANCH,start,end))
    cash=int(c.fetchone()["amount"])
    c.execute("""SELECT COALESCE(SUM(signed_amount_xaf),0) AS amount
                 FROM v3r_b_finance_drafts
                 WHERE tenant_id=%s AND branch_id=%s
                   AND channel='CASH'
                   AND effective_at>= %s AND effective_at < %s""",
              (TENANT,BRANCH,start,end))
    return cash+int(c.fetchone()["amount"])


@router.post("/reconciliation/draft")
def reconciliation_draft(body:ReconDraft, actor=Depends(auth)):
    _scope_body(body)
    start,end=shift_bounds(body.business_date,body.shift)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id FROM v3r_b_reconciliation_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                           AND business_date=%s AND shift=%s""",
                      (TENANT,BRANCH,body.business_date,body.shift))
            if c.fetchone():
                deny(409,"TEST_SHIFT_DRAFT_ALREADY_EXISTS")
            expected=_cash_in_window(c,start,end)
            variance=body.cashier_count_xaf-expected
            ident=uuid4()
            c.execute("""INSERT INTO v3r_b_reconciliation_drafts
                 (id,tenant_id,branch_id,business_date,shift,
                  cashier_count_xaf,system_cash_xaf,variance_xaf,recorded_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (ident,TENANT,BRANCH,body.business_date,body.shift,
                       body.cashier_count_xaf,expected,variance,actor["username"]))
    return {**meta(),"draftSaved":True,"ref":str(ident),
            "businessDate":body.business_date.isoformat(),"shift":body.shift,
            "systemCashXaf":expected,"cashierCountXaf":body.cashier_count_xaf,
            "varianceXaf":variance,"status":"RECON_DRAFT_TEST_NOT_CLOSED"}


@router.get("/reconciliation")
def reconciliations(tenant_id:int=TENANT,branch_id:int=BRANCH,actor=Depends(auth)):
    scope(tenant_id,branch_id)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id::text AS ref,business_date,shift,
                         cashier_count_xaf,system_cash_xaf,variance_xaf,
                         status,recorded_by
                         FROM v3r_b_reconciliation_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                         ORDER BY business_date DESC,shift LIMIT 100""",(TENANT,BRANCH))
            rows=c.fetchall()
    return {**meta(),"rows":rows,"status":"RECON_TEST_DRAFTS_UNAPPROVED"}


@router.get("/review/statement")
def reviewer_statement(business_date:date,shift:str,tenant_id:int=TENANT,
                       branch_id:int=BRANCH,actor=Depends(auth)):
    scope(tenant_id,branch_id)
    shift_bounds(business_date,shift)
    with finance_connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT id::text AS ref,business_date,shift,
                         cashier_count_xaf,system_cash_xaf,variance_xaf,
                         recorded_by,status
                         FROM v3r_b_reconciliation_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                           AND business_date=%s AND shift=%s""",
                      (TENANT,BRANCH,business_date,shift))
            row=c.fetchone()
    if row is None:
        deny(404,"TEST_FINANCE_STATEMENT_NOT_FOUND")
    return {**meta(),"statement":row,"statementPreparer":row["recorded_by"],
            "reviewerPrincipal":None,"requiresSeparateReviewer":True,
            "reviewStatus":"PENDING_TEST_FINANCE_REVIEW_NO_PC5",
            "authenticatedReviewPerformed":False}


@router.get("/month-close")
def month_close(period:str,tenant_id:int=TENANT,branch_id:int=BRANCH,actor=Depends(auth)):
    scope(tenant_id,branch_id)
    start,end=month_bounds(period)
    with finance_connect() as conn:
        with conn.cursor() as c:
            cash=_cash_in_window(c,start,end)
            c.execute("""SELECT kind,COALESCE(SUM(signed_amount_xaf),0) AS signed_total
                         FROM v3r_b_finance_drafts
                         WHERE tenant_id=%s AND branch_id=%s AND effective_at>= %s
                           AND effective_at<%s GROUP BY kind""",
                      (TENANT,BRANCH,start,end))
            categories={x["kind"]:int(x["signed_total"]) for x in c.fetchall()}
            c.execute("""SELECT COUNT(*) AS n FROM v3r_b_reconciliation_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                           AND business_date >= %s AND business_date < %s""",
                      (TENANT,BRANCH,start.date(),end.date()))
            recon_count=int(c.fetchone()["n"])
    return {**meta(),"period":period,"cashNetTestXaf":cash,
            "manualDraftSignedTotals":categories,"reconciliationDrafts":recon_count,
            "openingCashUnknown":True,"obligationsNotMapped":True,
            "arCarryUnverified":True,"reserveUnverified":True,
            "status":"MONTH_CLOSE_PREVIEW_NO_REAL_APPROVAL"}


@router.get("/reports")
def reports(as_of:datetime=Query(...),tenant_id:int=TENANT,branch_id:int=BRANCH,
            limit:int=Query(100,ge=1,le=200),actor=Depends(auth)):
    # Return test source rows, not a certified/full historical export.
    return entries(as_of=as_of,tenant_id=tenant_id,branch_id=branch_id,limit=limit,actor=actor)


@router.get("/reports/csv")
def test_csv(as_of:datetime=Query(...),tenant_id:int=TENANT,branch_id:int=BRANCH,
             actor=Depends(auth)):
    data=entries(as_of=as_of,tenant_id=tenant_id,branch_id=branch_id,limit=200,actor=actor)
    buf=StringIO()
    buf.write("SYNTHETIC_ONLY_NOT_A_REAL_WND_EXPORT\n")
    buf.write("LIMITED_TO_200_ROWS_UNPINNED_NOT_A_FULL_LEDGER_EXPORT\n")
    writer=csv.writer(buf)
    writer.writerow(["ref","kind","channel","signed_amount_xaf","effective_at","status"])
    def escaped(value):
        val=str(value)
        return "'"+val if re.match(r"^[\s]*[=+\-@]",val) else val
    for row in data["rows"]:
        writer.writerow([escaped(row[k]) for k in
                         ("ref","kind","channel","signed_amount_xaf","effective_at","status")])
    return PlainTextResponse(buf.getvalue(),media_type="text/csv",
        headers={"X-Data-Grade":GRADE,"Cache-Control":"no-store"})


@router.post("/review/approve")
def no_approval(actor=Depends(auth)):
    deny(403,"GENUINE_PC5_INDEPENDENT_REVIEWER_REQUIRED")


@router.post("/month-close/approve")
def no_close(actor=Depends(auth)):
    deny(403,"GENUINE_PC5_FINANCE_CLOSE_AUTHORITY_REQUIRED")
