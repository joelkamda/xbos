"""Aggregate M5.0-M5.5 read-only development and disposable acceptance gate."""
from __future__ import annotations
import argparse,subprocess,sys
from pathlib import Path
from sqlalchemy import text
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.domain.finance.m2_acceptance import validate_release_manifest as m2
from core.domain.finance.m3_acceptance import validate_release_manifest as m3
from core.domain.finance.m4_acceptance import EXPECTED_HEAD,validate_release_manifest as m4
from core.domain.finance.m5_acceptance import validate_release_manifest as m5
from database import engine
DATABASES=("xbos_track_b_m50_receivables_test","xbos_track_b_m51_payables_test","xbos_track_b_m52_commercial_terms_test","xbos_track_b_m53_earnings_test","xbos_track_b_m54_corrections_test")
SCRIPTS=("verify_m50_receivables.py","verify_m51_payables.py","verify_m52_commercial_terms.py","verify_m53_participant_earnings.py","verify_m54_correction_lifecycles.py")
EMPTY=("idempotency_records","kernel_source_records","financial_events","outbox_messages","journal_entries","journal_lines","financial_obligations","financial_obligation_lines","value_sources","payment_allocations","allocation_reversals","payment_settlements","provider_settlement_components")
def _development():
    if engine.url.database!="xbos_track_b_dev":raise RuntimeError("development database must be xbos_track_b_dev")
    counts=(m2(ROOT).checked_components,m3(ROOT).checked_components,m4(ROOT).checked_components,m5(ROOT))
    with engine.connect() as c:
        revision=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision!=EXPECTED_HEAD:raise RuntimeError(f"unexpected revision={revision}")
        if c.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()!=20:raise RuntimeError("catalog count differs")
        for table in EMPTY:
            if c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():raise RuntimeError(f"development table not empty={table}")
    print("database=xbos_track_b_dev");print(f"revision={EXPECTED_HEAD}");print(f"release_manifests=m2:{counts[0]},m3:{counts[1]},m4:{counts[2]},m5:{counts[3]}");print("m55_financial_lifecycle_development=PASS manifest=PASS development_empty=PASS")
def _status():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    base=make_url(engine.url.render_as_string(hide_password=False)).set(database="postgres")
    probe=create_engine(base,isolation_level="AUTOCOMMIT")
    try:
        with probe.connect() as c:
            for name in DATABASES:print(f"database={name} exists={str(bool(c.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),{'name':name}).scalar_one_or_none())).lower()}")
    finally:probe.dispose()
def _run():
    _development();_status();engine.dispose()
    for script in SCRIPTS:subprocess.run([sys.executable,str(ROOT/"scripts"/script),"create-and-verify"],cwd=ROOT,check=True)
    _development();_status();print("m55_financial_lifecycle_exit=PASS canonical_head=m46_provider_financials_015 manifest=PASS development=PASS statements=PASS m50_m54=PASS lifecycle_conformance=PASS tenant_scope=PASS deterministic=PASS dropped=true")
def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=("verify","status","create-and-verify"));a=p.parse_args()
    if a.command=="verify":_development()
    elif a.command=="status":_status()
    else:_run()
    return 0
if __name__=="__main__":raise SystemExit(main())
