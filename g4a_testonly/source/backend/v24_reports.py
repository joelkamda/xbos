"""Detached TEST-only keyset finance-draft report service. No protected/production effects."""
from __future__ import annotations
import base64, hashlib, hmac, json
from datetime import datetime, timezone
from uuid import UUID

KINDS={"INCOME_TEST","EXPENSE_TEST","MOVEMENT_TEST","CANCEL_TEST","FORWARD_AMENDMENT_TEST"}
CHANNELS={"CASH","MTN","ORANGE","BANK"}

class ReportCursorError(ValueError): pass

def stamp(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ReportCursorError("AWARE_TIMESTAMP_REQUIRED")
    return v.astimezone(timezone.utc).isoformat(timespec="microseconds")

def seal(payload,secret):
    if not isinstance(secret,bytes) or len(secret)<32:
        raise ReportCursorError("TEST_CURSOR_SECRET_INVALID")
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    return base64.urlsafe_b64encode(raw+hmac.digest(secret,raw,"sha256")).decode().rstrip("=")

def unseal(value,secret):
    if not isinstance(value,str) or len(value)>2000:
        raise ReportCursorError("CURSOR_INVALID")
    try:
        raw=base64.urlsafe_b64decode(value+"="*(-len(value)%4))
        if len(raw)<33 or not hmac.compare_digest(raw[-32:],hmac.digest(secret,raw[:-32],"sha256")):
            raise ValueError()
        state=json.loads(raw[:-32])
        if state.get("version")!=1: raise ValueError()
        return state
    except Exception as e:
        raise ReportCursorError("CURSOR_INVALID") from e

def page(connect,*,tenant,branch,as_of,secret,limit=100,kind=None,channel=None,cursor=None):
    if type(tenant)!=int or type(branch)!=int or min(tenant,branch)<1:
        raise ReportCursorError("SCOPE_INVALID")
    if type(limit)!=int or not 1<=limit<=500: raise ReportCursorError("LIMIT_INVALID")
    if kind is not None and kind not in KINDS: raise ReportCursorError("KIND_INVALID")
    if channel is not None and channel not in CHANNELS: raise ReportCursorError("CHANNEL_INVALID")
    when=stamp(as_of)
    scoped=dict(version=1,tenant=tenant,branch=branch,as_of=when,kind=kind,channel=channel)
    sql="""SELECT id::text AS ref,kind,channel,signed_amount_xaf,effective_at,created_at,status
           FROM v3r_b_finance_drafts
           WHERE tenant_id=%s AND branch_id=%s AND effective_at<=%s AND created_at<=%s"""
    params=[tenant,branch,as_of,as_of]
    if kind: sql+=" AND kind=%s";params.append(kind)
    if channel: sql+=" AND channel=%s";params.append(channel)
    if cursor:
        state=unseal(cursor,secret)
        if any(state.get(k)!=v for k,v in scoped.items()):
            raise ReportCursorError("CURSOR_SCOPE_OR_FILTER_MISMATCH")
        try:
            t=datetime.fromisoformat(state["last_at"])
            last_id=str(UUID(state["last_id"]))
            stamp(t)
        except (ValueError,KeyError,TypeError) as e:
            raise ReportCursorError("CURSOR_KEY_INVALID") from e
        sql+=" AND (effective_at,id)>(%s,%s::uuid)"
        params.extend((t,last_id))
    sql+=" ORDER BY effective_at ASC,id ASC LIMIT %s"
    params.append(limit+1)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,tuple(params))
            fetched=cur.fetchall()
    rows=fetched[:limit]
    more=len(fetched)>limit
    last=rows[-1] if more else None
    next_cursor=seal({**scoped,"last_at":stamp(last["effective_at"]),
                      "last_id":str(UUID(last["ref"]))},secret) if more else None
    return {"grade":"TEST_FINANCE_DRAFTS_ONLY_NOT_OFFICIAL_LEDGER",
            "rows":rows,"nextCursor":next_cursor,"hasMore":more,
            "asOf":when,"snapshotPinned":True,
            "snapshotRule":"created_at_and_effective_at_le_as_of; rows must be append-only",
            "fullHistoricalReport":False,"externalEffects":False}
