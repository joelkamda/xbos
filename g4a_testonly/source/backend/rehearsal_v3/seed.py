"""V24 fresh synthetic-only PG17 TEST binding, no original source database."""
import os
from psycopg import connect as pgconnect
from psycopg.rows import dict_row
DB="v24_native_d7_test"
PORT=55449
def config():
    key=os.environ.get("V24_SESSION_HMAC_HEX")
    if not key or len(key)!=64:raise RuntimeError("TEST_EPHEMERAL_SESSION_KEY_REQUIRED")
    return {"session_hmac_key_hex":key}
def connect():
    conn=pgconnect(host="127.0.0.1",port=PORT,user="postgres",
                   dbname=DB,connect_timeout=3,row_factory=dict_row)
    with conn.cursor() as c:
        c.execute("SELECT current_database() AS db,current_setting('port') AS port,current_setting('listen_addresses') AS addr")
        x=c.fetchone()
        if x["db"]!=DB or x["port"]!=str(PORT) or x["addr"]!="127.0.0.1":
            conn.close()
            raise RuntimeError("TEST_DB_IDENTITY_FENCE")
    return conn
LAB=None
