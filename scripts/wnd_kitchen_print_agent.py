#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse, ctypes, hashlib, json, os, subprocess, time, unicodedata
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, selectinload
# XBOS_REPO_ROOT_BOOTSTRAP
# Direct execution from scripts/ makes scripts the import root.
# Put the XBOS repository root first before importing root modules.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import database as database_module
import core.models_import  # XBOS_FULL_MODEL_REGISTRY
from core.api.orders.orders_controller import OrdersController
from core.domain.orders.models import Order, OrderItem

TENANT_ID=2
BRANCH_ID=1
STATE_DIR=Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "XBOS"
STATE_PATH=STATE_DIR / os.environ.get("XBOS_KITCHEN_STATE_FILE", "kitchen_print_state.json")
LOG_PATH=STATE_DIR / os.environ.get("XBOS_KITCHEN_LOG_FILE", "kitchen_print_agent.log")
VIRTUAL=("pdf","onenote","fax","xps","microsoft print")
THERMAL=("pos-80","pos80","80c","80mm","thermal","receipt")

def log(msg):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line=f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f: f.write(line+"\\n")
    except Exception:
        pass

def clean(v):
    s=unicodedata.normalize("NFKD", str(v or ""))
    return s.encode("ascii","ignore").decode("ascii").replace("\\r"," ").replace("\\n"," ").strip()

def printers():
    ps="$p=Get-CimInstance Win32_Printer | Select-Object Name,Default,WorkOffline,PortName | ConvertTo-Json -Compress; Write-Output $p"
    p=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip() or "Cannot enumerate Windows printers")
    raw=p.stdout.strip()
    if not raw: return []
    obj=json.loads(raw)
    if isinstance(obj,dict): obj=[obj]
    return [{"name":str(x.get("Name") or ""),"default":bool(x.get("Default")),"offline":bool(x.get("WorkOffline")),"port":str(x.get("PortName") or "")} for x in obj if x.get("Name")]

def choose_printer(explicit=None):
    ps=printers()
    if not ps: raise RuntimeError("No Windows printers installed")
    if explicit:
        for p in ps:
            if p["name"].lower()==explicit.lower(): return p
        raise RuntimeError("Requested printer not found: "+explicit)
    physical=[p for p in ps if not any(w in p["name"].lower() for w in VIRTUAL)]
    for p in physical:
        if any(h in p["name"].lower() for h in THERMAL): return p
    for p in physical:
        if p["default"]: return p
    for p in ps:
        if p["default"]: return p
    return physical[0] if physical else ps[0]

class DOC_INFO_1(ctypes.Structure):
    _fields_=[("pDocName",wintypes.LPWSTR),("pOutputFile",wintypes.LPWSTR),("pDatatype",wintypes.LPWSTR)]

def raw_spool(printer_name, data, doc_name):
    w=ctypes.WinDLL("winspool.drv")
    w.OpenPrinterW.argtypes=[wintypes.LPWSTR,ctypes.POINTER(wintypes.HANDLE),ctypes.c_void_p]
    w.OpenPrinterW.restype=wintypes.BOOL
    w.StartDocPrinterW.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(DOC_INFO_1)]
    w.StartDocPrinterW.restype=wintypes.DWORD
    w.StartPagePrinter.argtypes=[wintypes.HANDLE]; w.StartPagePrinter.restype=wintypes.BOOL
    w.WritePrinter.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    w.WritePrinter.restype=wintypes.BOOL
    h=wintypes.HANDLE()
    if not w.OpenPrinterW(printer_name,ctypes.byref(h),None): raise ctypes.WinError()
    doc_started=page_started=False
    try:
        info=DOC_INFO_1(doc_name,None,"RAW")
        job=w.StartDocPrinterW(h,1,ctypes.byref(info))
        if not job: raise ctypes.WinError()
        doc_started=True
        if not w.StartPagePrinter(h): raise ctypes.WinError()
        page_started=True
        buf=ctypes.create_string_buffer(data); written=wintypes.DWORD()
        if not w.WritePrinter(h,buf,len(data),ctypes.byref(written)): raise ctypes.WinError()
        if written.value!=len(data): raise RuntimeError(f"Short write {written.value}/{len(data)}")
        return int(job)
    finally:
        if page_started: w.EndPagePrinter(h)
        if doc_started: w.EndDocPrinter(h)
        w.ClosePrinter(h)

def escpos_bon(order,event):
    import textwrap

    width = 42
    separator = "-" * width

    def clean(value):
        text = str(value or "")
        text = text.replace("\r", " ").replace("\n", " ").strip()
        return text.encode("ascii", "ignore").decode("ascii")

    def add(buf, text=""):
        buf.extend(clean(text).encode("ascii", "ignore"))
        buf.extend(b"\n")

    def format_time(value):
        if not value:
            return ""
        try:
            if hasattr(value, "strftime"):
                return value.strftime("%d %b %Y  %H:%M")
            return str(value)[:16].replace("T", " ")
        except Exception:
            return clean(value)

    out = bytearray()

    # Initialize + center.
    out.extend(bytes([0x1B, 0x40]))
    out.extend(bytes([0x1B, 0x61, 0x01]))

    # Restaurant header: double width + height.
    out.extend(bytes([0x1D, 0x21, 0x11]))
    add(out, "WINE & DINE")

    # Kitchen title: normal size, bold.
    out.extend(bytes([0x1D, 0x21, 0x00]))
    out.extend(bytes([0x1B, 0x45, 0x01]))
    add(out, "KITCHEN BON")
    out.extend(bytes([0x1B, 0x45, 0x00]))

    event_label = clean(event or "NEW ORDER").replace("_", " ").upper()
    add(out, event_label)
    add(out, separator)

    # Left align.
    out.extend(bytes([0x1B, 0x61, 0x00]))

    # Large order number.
    out.extend(bytes([0x1B, 0x45, 0x01]))
    out.extend(bytes([0x1D, 0x21, 0x11]))
    add(out, f"ORDER #{order.get('order_id')}")
    out.extend(bytes([0x1D, 0x21, 0x00]))
    out.extend(bytes([0x1B, 0x45, 0x00]))

    created = format_time(order.get("created_at"))
    if created:
        add(out, f"TIME: {created}")

    waiter = clean(order.get("staff") or "").upper()
    if waiter:
        add(out, f"WAITER: {waiter}")

    state = clean(order.get("status") or "").replace("_", " ").upper()
    if state:
        add(out, f"STATE: {state}")

    add(out, separator)

    items = order.get("items") or []

    for item in items:
        quantity = int(item.get("quantity") or 1)
        name = clean(
            item.get("name_snapshot")
            or item.get("name")
            or "ITEM"
        ).upper()

        # Bold + double height, normal width.
        out.extend(bytes([0x1B, 0x45, 0x01]))
        out.extend(bytes([0x1D, 0x21, 0x10]))

        item_text = f"{quantity} x {name}"

        for line in textwrap.wrap(
            item_text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [item_text]:
            add(out, line)

        out.extend(bytes([0x1D, 0x21, 0x00]))
        out.extend(bytes([0x1B, 0x45, 0x00]))

        for modifier in item.get("modifiers") or []:
            modifier_type = clean(
                modifier.get("modifier_type")
                or modifier.get("type")
                or "NOTE"
            ).replace("_", " ").upper()

            modifier_name = clean(
                modifier.get("name_snapshot")
                or modifier.get("name")
                or ""
            ).upper()

            if not modifier_name:
                continue

            modifier_qty = int(modifier.get("quantity") or 1)
            qty_prefix = f"{modifier_qty} x " if modifier_qty > 1 else ""

            instruction = f">> {modifier_type}: {qty_prefix}{modifier_name}"

            out.extend(bytes([0x1B, 0x45, 0x01]))

            for line in textwrap.wrap(
                instruction,
                width=width - 2,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [instruction]:
                add(out, line)

            out.extend(bytes([0x1B, 0x45, 0x00]))

        add(out, "")

    add(out, separator)
    add(out, f"KITCHEN LINES: {len(items)}")

    out.extend(bytes([0x1B, 0x61, 0x01]))
    out.extend(bytes([0x1B, 0x45, 0x01]))
    add(out, "*** PREPARE NOW ***")
    out.extend(bytes([0x1B, 0x45, 0x00]))

    # Feed 4 lines, full cut, reset.
    out.extend(bytes([0x1B, 0x64, 0x04]))
    out.extend(bytes([0x1D, 0x56, 0x00]))
    out.extend(bytes([0x1B, 0x40]))

    return bytes(out)

def load_state():
    try:
        x=json.loads(STATE_PATH.read_text(encoding="utf-8")); x.setdefault("orders",{}); return x
    except Exception:
        return {"orders":{}}

def save_state(x):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(x,indent=2,sort_keys=True),encoding="utf-8")

def sig(order):
    payload={"id":order["order_id"],"status":order.get("status"),"items":[{"id":i.get("order_item_id"),"qty":i.get("quantity"),"name":i.get("name_snapshot"),"modifiers":i.get("modifiers") or []} for i in order["items"]]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()

def modifiers(item):
    out=[]
    for m in getattr(item,"modifiers",None) or []:
        out.append({"modifier_type":getattr(m,"modifier_type","modifier"),"name_snapshot":getattr(m,"name_snapshot",""),"quantity":int(getattr(m,"quantity",1) or 1)})
    return out

def queue(session,new_paid_since=None):
    c=OrdersController()
    rows=(session.query(Order)
          .options(selectinload(Order.items).selectinload(OrderItem.modifiers))
          .filter(Order.tenant_id==TENANT_ID,Order.branch_id==BRANCH_ID)
          .order_by(Order.id.asc()).all())
    out=[]
    for order in rows:
        status=str(getattr(order,"status","") or "").strip().lower()
        pending=status in {"pending_payment","ready","preparing","in_progress"}
        new_paid=False
        if status=="paid" and new_paid_since is not None and getattr(order,"created_at",None):
            dt=order.created_at
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            new_paid=dt.astimezone(timezone.utc)>=new_paid_since
        if not pending and not new_paid: continue
        items=[]
        for item in order.items or []:
            route=c._fulfillment_payload_for_item(session,tenant_id=TENANT_ID,atomic_unit_id=item.atomic_unit_id,stored_status=getattr(item,"fulfillment_status",None))
            if not route.get("requires_fulfillment"): continue
            st=str(route.get("fulfillment_status") or "waiting").lower()
            if st in {"ready","served","fulfilled","cancelled","voided"}: continue
            items.append({"order_item_id":item.id,"atomic_unit_id":item.atomic_unit_id,"name_snapshot":item.name_snapshot,"quantity":int(item.quantity or 0),"modifiers":modifiers(item)})
        if not items: continue
        staff=""
        try:
            staff=c._user_display_name(session,tenant_id=TENANT_ID,user_id=getattr(order,"created_by_user_id",None)) or ""
        except Exception:
            pass
        out.append({"order_id":int(order.id),"status":status or "pending_payment","created_at":getattr(order,"created_at",None),"staff":staff,"items":items})
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--database",default=os.environ.get("XBOS_KITCHEN_DB","xbos"))
    ap.add_argument("--printer")
    ap.add_argument("--once",action="store_true")
    ap.add_argument("--force-current",action="store_true")
    ap.add_argument("--watch",action="store_true")
    ap.add_argument("--poll-seconds",type=float,default=2.0)
    a=ap.parse_args()
    p=choose_printer(a.printer)
    log(f"PRINTER_SELECTED name={p['name']} default={p['default']} offline={p['offline']} port={p['port']}")
    engine=create_engine(database_module.engine.url.set(database=a.database),pool_pre_ping=True)
    state=load_state(); started=datetime.now(timezone.utc)-timedelta(minutes=2); first=True
    try:
        while True:
            with Session(engine) as s: orders=queue(s,started)
            if first: log(f"QUEUE_SNAPSHOT orders={len(orders)} database={a.database}")
            for order in orders:
                key=str(order["order_id"]); signature=sig(order); prev=state["orders"].get(key,{}).get("signature")
                event=None
                if a.force_current and first: event="CURRENT QUEUE"
                elif prev is None: event="NEW ORDER"
                elif prev!=signature:
                    state["orders"][key]["signature"]=signature
                    state["orders"][key]["last_seen_at"]=datetime.now(timezone.utc).isoformat()
                    event=None
                    log(f"SUPPRESSED_REPRINT order={order['order_id']} reason=already_printed")
                if event:
                    job=raw_spool(p["name"],escpos_bon(order,event),f"WND Kitchen Bon #{order['order_id']}")
                    log(f"PRINTED order={order['order_id']} event={event} items={len(order['items'])} job={job} printer={p['name']}")
                    state["orders"][key]={"signature":signature,"printed_at":datetime.now(timezone.utc).isoformat(),"event":event}
                    save_state(state)
            first=False
            if a.once or not a.watch: break
            time.sleep(max(1.0,a.poll_seconds))
    finally:
        engine.dispose()

if __name__=="__main__":
    main()
