"""Integrated real PostgreSQL functional tests of disposable TEST schema.
Creates nonpersonal test order and verifies database persistence.
Does NOT certify production PC5, WND schema parity, payments or G3/G4.
"""
import json
from pathlib import Path
from uuid import uuid4
import unittest
from fastapi.testclient import TestClient
from .api import app
from .seed import connect, LAB

class RealV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)
        secret=(LAB/"private/operator_login.txt").read_text(encoding="utf-8")
        cls.password=next(v.split(": ",1)[1] for v in secret.splitlines() if v.startswith("password: "))
        cls.headers={}
        cls.order_id=None
        cls.ticket_id=None
        cls.idempotency="INTEGRATION-"+uuid4().hex
        cls.start_inventory=None

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def request(self,method,path,**kwargs):
        return self.client.request(method,path,headers=self.headers,**kwargs)

    def test_01_health_separate_pg(self):
        r=self.client.get("/api/v3/health")
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["port"],"55438")
        self.assertEqual(r.json()["database"],"xcomp_v3_rehearsal_20261114")
        self.assertFalse(r.json()["pc5Admitted"])

    def test_02_protected_catalog_before_login(self):
        r=self.client.get("/api/v3/catalog")
        self.assertEqual(r.status_code,401)

    def test_03_wrong_operator_password(self):
        r=self.client.post("/api/v3/session",json={"username":"operator","password":"bad"})
        self.assertEqual(r.status_code,401)

    def test_04_real_signed_session(self):
        r=self.client.post("/api/v3/session",json={"username":"operator","password":self.password})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["role"],"REHEARSAL_ADMIN")
        self.assertFalse(r.json()["pc5"])
        self.__class__.headers={"X-Rehearsal-Token":r.json()["token"]}
        self.assertEqual(self.request("GET","/api/v3/summary").status_code,200)

    def test_05_catalog_56_real_pg_rows(self):
        r=self.request("GET","/api/v3/catalog?zone=VIP")
        self.assertEqual(r.status_code,200,r.text)
        self.assertGreaterEqual(r.json()["count"],56)
        self.assertEqual(r.json()["zone"],"VIP")
        self.assertEqual(r.json()["tenant"],910001)
        self.assertIn("source_revision",r.json()["items"][0])

    def test_06_real_inventory_before_order(self):
        r=self.request("GET","/api/v3/inventory")
        self.assertEqual(r.status_code,200,r.text)
        item=next(x for x in r.json()["items"] if x["sku"]=="TEST-WND-001")
        self.__class__.start_inventory=item["stock_qty"]
        self.assertIsInstance(self.start_inventory,int)

    def test_07_atomic_real_pg_order_and_receivable(self):
        r=self.request("POST","/api/v3/orders",json={
            "idempotency_key":self.idempotency,"zone":"VIP",
            "lines":[{"sku":"TEST-WND-001","quantity":2},{"sku":"TEST-WND-026","quantity":1}]})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["persisted"])
        self.assertFalse(r.json()["paid"])
        self.assertEqual(len(r.json()["kitchenSkus"]),1)
        self.assertEqual(r.json()["totalXaf"],11800)
        self.__class__.order_id=r.json()["orderId"]
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status,amount_xaf,zone FROM v3r_orders WHERE id=%s",
                            (self.order_id,))
                row=cur.fetchone()
                self.assertEqual(row["amount_xaf"],11800)
                self.assertEqual(row["status"],"UNPAID_TEST")
                self.assertEqual(row["zone"],"VIP")
                cur.execute("SELECT COUNT(*) AS n FROM v3r_finance_events WHERE order_id=%s AND kind='RECEIVABLE_TEST'",
                            (self.order_id,))
                self.assertEqual(cur.fetchone()["n"],1)

    def test_08_idempotency_no_duplicate_stock_or_finance(self):
        r=self.request("POST","/api/v3/orders",json={
            "idempotency_key":self.idempotency,"zone":"VIP",
            "lines":[{"sku":"TEST-WND-001","quantity":2},{"sku":"TEST-WND-026","quantity":1}]})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["replayed"])
        self.assertEqual(r.json()["orderId"],self.order_id)
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stock_qty FROM v3r_products WHERE sku='TEST-WND-001'")
                self.assertEqual(cur.fetchone()["stock_qty"],self.start_inventory-2)
                cur.execute("SELECT COUNT(*) AS n FROM v3r_stock_movements WHERE order_id=%s",(self.order_id,))
                self.assertEqual(cur.fetchone()["n"],1)

    def test_09_negative_balance_denied(self):
        r=self.request("POST","/api/v3/orders",json={
            "idempotency_key":"EXCESS-"+uuid4().hex,"zone":"MAIN",
            "lines":[{"sku":"TEST-WND-020","quantity":20}]})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(r.json()["detail"],"NEGATIVE_STOCK_BALANCE_DENIED")

    def test_10_unknown_sku_denied(self):
        r=self.request("POST","/api/v3/orders",json={
            "idempotency_key":"BADSKU-"+uuid4().hex,"zone":"MAIN",
            "lines":[{"sku":"TEST-WND-NONEXISTENT","quantity":1}]})
        self.assertEqual(r.status_code,422)

    def test_11_real_kitchen_persisted(self):
        r=self.request("GET","/api/v3/kitchen")
        self.assertEqual(r.status_code,200,r.text)
        tickets=[x for x in r.json()["tickets"] if x["order_id"]==self.order_id]
        self.assertEqual(len(tickets),1)
        self.assertEqual(tickets[0]["status"],"PENDING")
        self.__class__.ticket_id=tickets[0]["id"]
        x=self.request("POST","/api/v3/kitchen/"+self.ticket_id+"/ready")
        self.assertEqual(x.status_code,200,x.text)
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM v3r_kitchen_tickets WHERE id=%s",(self.ticket_id,))
                self.assertEqual(cur.fetchone()["status"],"READY")

    def test_12_real_test_cash_finance(self):
        r=self.request("POST","/api/v3/orders/"+self.order_id+"/cash-test")
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["noActualMoney"])
        r=self.request("GET","/api/v3/finance")
        self.assertEqual(r.status_code,200)
        self.assertGreaterEqual(r.json()["cashTestXaf"],11800)
        self.assertFalse(r.json()["realPayment"])
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM v3r_orders WHERE id=%s",(self.order_id,))
                self.assertEqual(cur.fetchone()["status"],"CASH_SETTLED_TEST")
                cur.execute("SELECT COUNT(*) AS n FROM v3r_finance_events WHERE order_id=%s",(self.order_id,))
                self.assertEqual(cur.fetchone()["n"],2)
        r=self.request("POST","/api/v3/orders/"+self.order_id+"/cash-test")
        self.assertEqual(r.status_code,409)

    def test_13_real_product_admin_persisted(self):
        r=self.request("POST","/api/v3/products",json={
            "name":"Rehearsal Special","category":"TEST ADDITIONS","family":"kitchen",
            "base_xaf":3700,"stock_qty":None})
        self.assertEqual(r.status_code,200,r.text)
        sku=r.json()["sku"]
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM v3r_prices WHERE sku=%s",(sku,))
                self.assertEqual(cur.fetchone()["n"],3)

    def test_14_forged_token_denied(self):
        token=self.headers["X-Rehearsal-Token"]
        r=self.client.get("/api/v3/orders",headers={"X-Rehearsal-Token":token[:-5]+"zzzzz"})
        self.assertEqual(r.status_code,401)

    def test_15_revocation_is_immediate(self):
        token=self.headers["X-Rehearsal-Token"]
        r=self.request("POST","/api/v3/session/revoke")
        self.assertEqual(r.status_code,200,r.text)
        r=self.client.get("/api/v3/catalog",headers={"X-Rehearsal-Token":token})
        self.assertEqual(r.status_code,401)

if __name__=="__main__":
    unittest.main(verbosity=2)
