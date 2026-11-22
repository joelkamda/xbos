"""V24 exclusively synthetic native source fixture: TEST restaurant, no PII."""
import hashlib,secrets
from rehearsal_v3.seed import connect
def main():
    with connect() as db:
        with db.cursor() as c:
            for user,role in (
                ("merchant","MERCHANT_TEST"),
                ("reviewer","REVIEWER_TEST"),
                ("cashier","CASHIER_TEST"),
                ("closer","CLOSER_TEST")):
                pwd="V24-ONLY-"+user+"-synthetic"
                salt=secrets.token_hex(16)
                digest=hashlib.pbkdf2_hmac("sha256",pwd.encode(),bytes.fromhex(salt),185000).hex()
                c.execute("INSERT INTO v3r_operator(username,salt,hash,role) VALUES(%s,%s,%s,%s)",
                          (user,salt,digest,role))
            for sku,name,cat,family,stock,main in (
                ("TEST-DRINK-01","Synthetic test fruit juice","DRINK","bar",45,1200),
                ("TEST-FOOD-01","Synthetic test fish plate","MAIN DISH","kitchen",None,4500)):
                c.execute("INSERT INTO v3r_products(sku,name,category,family,stock_qty) VALUES(%s,%s,%s,%s,%s)",
                          (sku,name,cat,family,stock))
                for zone,amount in (("MAIN",main),("VIP",main+700),("BAR",main+300)):
                    c.execute("INSERT INTO v3r_prices(sku,zone,amount_xaf) VALUES(%s,%s,%s)",
                              (sku,zone,amount))
        db.commit()
    print("V24_FRESH_SYNTHETIC_PG17_FIXTURE=PASS")
if __name__=="__main__": main()
