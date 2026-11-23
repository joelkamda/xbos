"""Isolated SQLite TEST stock count/reconciliation, movement journal, and COGS policy.
No historical source-stock repair, protected DB access or real Finance posting.
"""
import sqlite3,json
from datetime import datetime,timezone
from uuid import uuid4
class StockError(ValueError):pass
class TestStock:
 def __init__(self,db):
  self.db=db;db.row_factory=sqlite3.Row
  db.executescript("""
  CREATE TABLE IF NOT EXISTS sku_test(
     tenant INTEGER, sku TEXT, initial_qty INTEGER NOT NULL,
     category TEXT NOT NULL,unit_cost_xaf INTEGER NOT NULL,
     PRIMARY KEY(tenant,sku));
  CREATE TABLE IF NOT EXISTS movement_test(
     id TEXT PRIMARY KEY,tenant INTEGER,sku TEXT,delta INTEGER NOT NULL,
     kind TEXT NOT NULL,ref TEXT NOT NULL,at TEXT NOT NULL,
     UNIQUE(tenant,sku,ref));
  CREATE TABLE IF NOT EXISTS count_draft_test(
     id TEXT PRIMARY KEY,tenant INTEGER,sku TEXT,observed_qty INTEGER,
     status TEXT NOT NULL,revision INTEGER NOT NULL,
     created_by TEXT NOT NULL,approved_by TEXT);
  CREATE TABLE IF NOT EXISTS count_audit_test(
     id TEXT PRIMARY KEY,draft_id TEXT,action TEXT,actor TEXT,
     revision INTEGER,payload TEXT);
  """)
 def seed(self,tenant,sku,qty,category,cost):
  if category not in {"DRINK","FOOD","NONSTOCK"} or any(type(x)!=int for x in (tenant,qty,cost)) or tenant<1 or cost<0:
   raise StockError("SKU_INVALID")
  with self.db:
   self.db.execute("INSERT INTO sku_test VALUES(?,?,?,?,?)",(tenant,sku,qty,category,cost))
 def _sku(self,tenant,sku):
  row=self.db.execute("SELECT * FROM sku_test WHERE tenant=? AND sku=?",(tenant,sku)).fetchone()
  if not row:raise StockError("SKU_SCOPE_DENIED")
  return dict(row)
 def quantity(self,tenant,sku,as_of=None):
  item=self._sku(tenant,sku)
  sql="SELECT COALESCE(SUM(delta),0) AS n FROM movement_test WHERE tenant=? AND sku=?"
  args=[tenant,sku]
  if as_of is not None:sql+=" AND at<=?";args.append(as_of)
  n=int(self.db.execute(sql,args).fetchone()["n"])
  return item["initial_qty"]+n
 def movement(self,tenant,sku,delta,ref,kind,at):
  item=self._sku(tenant,sku)
  if item["category"]=="NONSTOCK":raise StockError("NONSTOCK_MOVEMENT_DENIED")
  if type(delta)!=int or not delta or not ref:raise StockError("MOVEMENT_INVALID")
  if self.db.execute("SELECT 1 FROM movement_test WHERE tenant=? AND sku=? AND ref=?",(tenant,sku,ref)).fetchone():
   raise StockError("DUPLICATE_MOVEMENT_DENIED")
  with self.db:
   self.db.execute("INSERT INTO movement_test VALUES(?,?,?,?,?,?,?)",
                   (str(uuid4()),tenant,sku,delta,kind,ref,at))
  return self.quantity(tenant,sku)
 def cogs(self,tenant,sku,qty):
  item=self._sku(tenant,sku)
  if type(qty)!=int or qty<1:raise StockError("QUANTITY_INVALID")
  if item["category"]=="DRINK":return {"autoCostXaf":qty*item["unit_cost_xaf"],"policy":"DRINK_AUTO_TEST"}
  return {"autoCostXaf":0,"policy":"FOOD_MANUAL_TEST" if item["category"]=="FOOD" else "NO_STOCK_COGS"}
 def _draft(self,tenant,did):
  r=self.db.execute("SELECT * FROM count_draft_test WHERE tenant=? AND id=?",(tenant,did)).fetchone()
  if not r:raise StockError("DRAFT_SCOPE_DENIED")
  return dict(r)
 def _audit(self,r,action,actor):
  self.db.execute("INSERT INTO count_audit_test VALUES(?,?,?,?,?,?)",
       (str(uuid4()),r["id"],action,actor,r["revision"],json.dumps(r,sort_keys=True)))
 def draft(self,tenant,sku,actor):
  self._sku(tenant,sku)
  did=str(uuid4())
  with self.db:
   self.db.execute("INSERT INTO count_draft_test VALUES(?,?,?,NULL,'DRAFT_TEST',1,?,NULL)",
                   (did,tenant,sku,actor))
   self._audit(self._draft(tenant,did),"CREATE",actor)
  return self._draft(tenant,did)
 def save_count(self,tenant,did,actor,revision,count):
  r=self._draft(tenant,did)
  if r["revision"]!=revision:raise StockError("REVISION_CONFLICT")
  if r["status"]!="DRAFT_TEST":raise StockError("DRAFT_LOCKED")
  if type(count)!=int or count<0:raise StockError("COUNT_INVALID")
  with self.db:
   self.db.execute("UPDATE count_draft_test SET observed_qty=?,revision=revision+1 WHERE id=?",
                   (count,did))
   self._audit(self._draft(tenant,did),"SAVE_COUNT",actor)
  return self._draft(tenant,did)
 def approve(self,tenant,did,actor,revision,at):
  r=self._draft(tenant,did)
  if revision!=r["revision"]:raise StockError("REVISION_CONFLICT")
  if r["status"]!="DRAFT_TEST" or r["observed_qty"] is None:raise StockError("COUNT_NOT_READY")
  if actor==r["created_by"]:raise StockError("INDEPENDENT_APPROVER_REQUIRED")
  change=r["observed_qty"]-self.quantity(tenant,r["sku"])
  # One atomic SQLite TEST transaction for adjustment and approval; no nested commit.
  with self.db:
   if change:
    self.db.execute("INSERT INTO movement_test VALUES(?,?,?,?,?,?,?)",
                    (str(uuid4()),tenant,r["sku"],change,"COUNT_ADJUSTMENT_TEST","count:"+did,at))
   self.db.execute("UPDATE count_draft_test SET status='APPROVED_TEST',revision=revision+1,approved_by=? WHERE id=?",
                   (actor,did))
   self._audit(self._draft(tenant,did),"APPROVE",actor)
  return {"draftId":did,"adjustment":change,"newQty":self.quantity(tenant,r["sku"]),
          "state":"APPROVED_TEST","financePosted":False}
