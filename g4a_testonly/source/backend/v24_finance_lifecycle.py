"""Isolated SQLite TEST Finance journal, actor review and close state machine.
No canonical XBOS/WND posting, genuine PC5, or production financial effect.
"""
import sqlite3
from uuid import uuid4
from datetime import datetime,timezone
class FinanceError(ValueError):pass
class TestFinance:
 def __init__(self,db):
  self.db=db;db.row_factory=sqlite3.Row
  db.executescript("""
  CREATE TABLE IF NOT EXISTS period_test(
   tenant INTEGER,period TEXT,status TEXT NOT NULL,revision INTEGER NOT NULL,
   prepared_by TEXT,reviewed_by TEXT,closed_by TEXT,carry_xaf INTEGER,
   PRIMARY KEY(tenant,period));
  CREATE TABLE IF NOT EXISTS entry_test(
   id TEXT PRIMARY KEY,tenant INTEGER,period TEXT,amount_xaf INTEGER NOT NULL,
   channel TEXT NOT NULL,kind TEXT NOT NULL,idempotency TEXT NOT NULL,
   actor TEXT NOT NULL,original_id TEXT,created_at TEXT NOT NULL,
   UNIQUE(tenant,idempotency));
  CREATE TABLE IF NOT EXISTS audit_test(
   seq INTEGER PRIMARY KEY AUTOINCREMENT,tenant INTEGER,period TEXT,
   action TEXT,actor TEXT,reference TEXT,at TEXT);
  """)
 def _audit(self,tenant,period,action,actor,ref):
  self.db.execute("INSERT INTO audit_test(tenant,period,action,actor,reference,at) VALUES(?,?,?,?,?,?)",
                  (tenant,period,action,actor,ref,datetime.now(timezone.utc).isoformat()))
 def period(self,tenant,period):
  p=self.db.execute("SELECT * FROM period_test WHERE tenant=? AND period=?",(tenant,period)).fetchone()
  if not p:raise FinanceError("PERIOD_NOT_INITIALIZED")
  return dict(p)
 def open(self,tenant,period,actor,opening_xaf=0):
  if type(tenant)!=int or tenant<1 or len(period)!=7 or type(opening_xaf)!=int:
   raise FinanceError("PERIOD_INVALID")
  with self.db:
   self.db.execute("INSERT INTO period_test VALUES(?,?,'OPEN_TEST',1,?,NULL,NULL,?)",
                   (tenant,period,actor,opening_xaf))
   self._audit(tenant,period,"OPEN",actor,period)
 def net(self,tenant,period):
  p=self.period(tenant,period)
  n=self.db.execute("SELECT COALESCE(SUM(amount_xaf),0) FROM entry_test WHERE tenant=? AND period=?",
                    (tenant,period)).fetchone()[0]
  return p["carry_xaf"]+n
 def post_test(self,tenant,period,amount,channel,kind,key,actor,original_id=None):
  p=self.period(tenant,period)
  if p["status"]!="OPEN_TEST":raise FinanceError("PERIOD_LOCKED")
  if type(amount)!=int or amount==0 or not actor or not key or channel not in {"CASH","ORANGE","MTN","BANK"}:
   raise FinanceError("ENTRY_INVALID")
  if kind not in {"INCOME_TEST","EXPENSE_TEST","CANCELLATION_TEST","FORWARD_AMENDMENT_TEST"}:
   raise FinanceError("KIND_INVALID")
  ident=str(uuid4())
  with self.db:
   try:
    self.db.execute("INSERT INTO entry_test VALUES(?,?,?,?,?,?,?,?,?,?)",
      (ident,tenant,period,amount,channel,kind,key,actor,original_id,datetime.now(timezone.utc).isoformat()))
   except sqlite3.IntegrityError as ex:raise FinanceError("DUPLICATE_ENTRY_DENIED") from ex
   self._audit(tenant,period,kind,actor,ident)
  return ident
 def cancel(self,tenant,period,original_id,actor,reason):
  if len(reason.strip())<4:raise FinanceError("CANCEL_REASON_REQUIRED")
  row=self.db.execute("SELECT * FROM entry_test WHERE tenant=? AND period=? AND id=?",
                      (tenant,period,original_id)).fetchone()
  if not row:raise FinanceError("ORIGINAL_NOT_FOUND")
  if row["kind"]=="CANCELLATION_TEST":raise FinanceError("CANNOT_CANCEL_CANCELLATION")
  if self.db.execute("SELECT 1 FROM entry_test WHERE original_id=?",(original_id,)).fetchone():
   raise FinanceError("ALREADY_CANCELLED")
  return self.post_test(tenant,period,-row["amount_xaf"],row["channel"],
                        "CANCELLATION_TEST","cancel:"+original_id,actor,original_id)
 def prepare(self,tenant,period,actor):
  p=self.period(tenant,period)
  if p["status"]!="OPEN_TEST":raise FinanceError("STATE_INVALID")
  with self.db:
   self.db.execute("UPDATE period_test SET status='PREPARED_TEST',prepared_by=?,revision=revision+1 WHERE tenant=? AND period=?",
                   (actor,tenant,period))
   self._audit(tenant,period,"PREPARE",actor,period)
  return self.period(tenant,period)
 def review(self,tenant,period,actor,revision):
  p=self.period(tenant,period)
  if p["revision"]!=revision:raise FinanceError("REVISION_CONFLICT")
  if p["status"]!="PREPARED_TEST":raise FinanceError("STATE_INVALID")
  if actor==p["prepared_by"]:raise FinanceError("INDEPENDENT_REVIEWER_REQUIRED")
  with self.db:
   self.db.execute("UPDATE period_test SET status='REVIEWED_TEST',reviewed_by=?,revision=revision+1 WHERE tenant=? AND period=?",
                   (actor,tenant,period))
   self._audit(tenant,period,"REVIEW",actor,period)
  return self.period(tenant,period)
 def close(self,tenant,period,actor,revision,next_period):
  p=self.period(tenant,period)
  if p["revision"]!=revision:raise FinanceError("REVISION_CONFLICT")
  if p["status"]!="REVIEWED_TEST":raise FinanceError("REVIEW_REQUIRED")
  if actor in {p["prepared_by"],p["reviewed_by"]}:raise FinanceError("SEPARATE_CLOSER_REQUIRED")
  carried=self.net(tenant,period)
  with self.db:
   self.db.execute("INSERT INTO period_test VALUES(?,?,'OPEN_TEST',1,?,NULL,NULL,?)",
                   (tenant,next_period,actor,carried))
   self.db.execute("UPDATE period_test SET status='CLOSED_TEST',closed_by=?,revision=revision+1 WHERE tenant=? AND period=?",
                   (actor,tenant,period))
   self._audit(tenant,period,"CLOSE",actor,next_period)
  return {"status":"CLOSED_TEST","nextOpeningXaf":carried,
          "financePosted":False,"genuinePC5":False}
 def amend_forward(self,tenant,closed_period,current_period,amount,channel,actor,key):
  if self.period(tenant,closed_period)["status"]!="CLOSED_TEST":
   raise FinanceError("SOURCE_PERIOD_NOT_CLOSED")
  return self.post_test(tenant,current_period,amount,channel,
                 "FORWARD_AMENDMENT_TEST",key,actor,closed_period)
 def audit(self,tenant,period):
  return [dict(r) for r in self.db.execute(
   "SELECT * FROM audit_test WHERE tenant=? AND period=? ORDER BY seq",(tenant,period))]
