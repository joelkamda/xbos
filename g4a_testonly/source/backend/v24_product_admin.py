"""SQLite-only TEST prototype for merchant product draft/review/publish/deactivate.
No native PA/PK/PC5 release signing. Zero protected or real WND writes.
"""
import json,sqlite3
from datetime import datetime,timezone
from uuid import uuid4
class ProductError(ValueError):pass
class ProductAdmin:
    def __init__(self,conn):
        self.db=conn
        self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS product_test(
          id TEXT PRIMARY KEY,tenant INTEGER NOT NULL,name TEXT NOT NULL,
          category TEXT,unit TEXT,type TEXT,main_xaf INTEGER,vip_xaf INTEGER,bar_xaf INTEGER,
          stock INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,revision INTEGER NOT NULL,
          creator TEXT NOT NULL,reviewer TEXT);
        CREATE TABLE IF NOT EXISTS product_test_history(
          product_id TEXT NOT NULL,revision INTEGER NOT NULL,action TEXT NOT NULL,
          actor TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(product_id,revision));""")
    def _get(self,tenant,pid):
        if type(tenant)!=int or tenant<1:raise ProductError("TENANT_INVALID")
        r=self.db.execute("SELECT * FROM product_test WHERE id=? AND tenant=?",(pid,tenant)).fetchone()
        if not r:raise ProductError("PRODUCT_NOT_FOUND_OR_WRONG_TENANT")
        return dict(r)
    def _event(self,r,action,actor):
        self.db.execute("INSERT INTO product_test_history VALUES(?,?,?,?,?,?)",
                        (r["id"],r["revision"],action,actor,
                         json.dumps(r,sort_keys=True),datetime.now(timezone.utc).isoformat()))
    def draft(self,tenant,name,actor):
        if type(tenant)!=int or tenant<1 or not name or not name.strip() or not actor:
            raise ProductError("DRAFT_INVALID")
        pid=str(uuid4())
        with self.db:
            self.db.execute("""INSERT INTO product_test(id,tenant,name,status,revision,creator)
                               VALUES(?,?,?,'DRAFT_TEST',1,?)""",
                            (pid,tenant,name.strip(),actor))
            self._event(self._get(tenant,pid),"DRAFT",actor)
        return self._get(tenant,pid)
    def revise(self,tenant,pid,actor,expected_revision,**values):
        permitted={"name","category","unit","type","main_xaf","vip_xaf","bar_xaf","stock"}
        if not values or set(values)-permitted or not actor:raise ProductError("EDIT_INVALID")
        r=self._get(tenant,pid)
        if r["revision"]!=expected_revision:raise ProductError("REVISION_CONFLICT")
        if r["status"] not in {"DRAFT_TEST","REVIEW_REQUESTED_TEST"}:raise ProductError("PUBLISHED_IMMUTABLE")
        for field in ("main_xaf","vip_xaf","bar_xaf"):
            if field in values and (type(values[field])!=int or values[field]<0):
                raise ProductError("PRICE_INVALID")
        if "stock" in values and type(values["stock"])!=int:raise ProductError("STOCK_INVALID")
        if "name" in values and not values["name"].strip():raise ProductError("NAME_INVALID")
        assigns=", ".join(k+"=?" for k in values)
        with self.db:
            self.db.execute("UPDATE product_test SET "+assigns+",revision=revision+1,status='DRAFT_TEST',reviewer=NULL WHERE id=? AND tenant=?",
                            (*values.values(),pid,tenant))
            updated=self._get(tenant,pid)
            self._event(updated,"REVISE",actor)
        return updated
    def submit(self,tenant,pid,actor,expected_revision):
        r=self._get(tenant,pid)
        if r["revision"]!=expected_revision:raise ProductError("REVISION_CONFLICT")
        if r["status"]!="DRAFT_TEST":raise ProductError("STATE_INVALID")
        missing=[x for x in ("category","unit","type","main_xaf","vip_xaf","bar_xaf") if r[x] is None or r[x]==""]
        if missing:raise ProductError("INCOMPLETE_CLASSIFICATION_OR_ZONE_PRICES:"+",".join(missing))
        with self.db:
            self.db.execute("UPDATE product_test SET status='REVIEW_REQUESTED_TEST',revision=revision+1 WHERE id=?",(pid,))
            updated=self._get(tenant,pid)
            self._event(updated,"REQUEST_REVIEW",actor)
        return updated
    def publish(self,tenant,pid,reviewer,expected_revision):
        r=self._get(tenant,pid)
        if r["revision"]!=expected_revision:raise ProductError("REVISION_CONFLICT")
        if r["status"]!="REVIEW_REQUESTED_TEST":raise ProductError("REVIEW_REQUIRED")
        if not reviewer or reviewer==r["creator"]:raise ProductError("INDEPENDENT_REVIEWER_REQUIRED")
        with self.db:
            self.db.execute("UPDATE product_test SET status='PUBLISHED_TEST',reviewer=?,revision=revision+1 WHERE id=?",
                            (reviewer,pid))
            updated=self._get(tenant,pid)
            self._event(updated,"PUBLISH_TEST",reviewer)
        return updated
    def deactivate(self,tenant,pid,actor,expected_revision):
        r=self._get(tenant,pid)
        if r["revision"]!=expected_revision:raise ProductError("REVISION_CONFLICT")
        if r["status"]!="PUBLISHED_TEST":raise ProductError("ONLY_PUBLISHED_CAN_DEACTIVATE")
        with self.db:
            self.db.execute("UPDATE product_test SET status='INACTIVE_TEST',revision=revision+1 WHERE id=?",(pid,))
            updated=self._get(tenant,pid)
            self._event(updated,"DEACTIVATE_TEST",actor)
        return updated
    def visible_pos(self,tenant):
        return [dict(r) for r in self.db.execute("SELECT * FROM product_test WHERE tenant=? AND status='PUBLISHED_TEST' ORDER BY name,id",(tenant,))]
    def history(self,tenant,pid):
        self._get(tenant,pid)
        return [dict(r) for r in self.db.execute("SELECT revision,action,actor,payload FROM product_test_history WHERE product_id=? ORDER BY revision",(pid,))]
