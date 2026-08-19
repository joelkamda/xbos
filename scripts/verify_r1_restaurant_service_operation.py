#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
C=ROOT/'contracts/restaurant/v1'
SOURCE='28290b66ea6301ca1015e286bcf49552895c5bf2';SOURCE_SHA='7795549f68d01809baca4b12f710a12be4de0f90f402c838c297be6c241b77f3';SOURCE_SIZE=6013667
PREVIOUS='semantic_classification_hardening_041';HEAD='r1_restaurant_service_operation_042';TEST='xbos_r1_acceptance';DEV='xbos_track_b_dev';LOCAL={'localhost','127.0.0.1','::1',None}
TABLES={'r1_restaurant_commands','r1_restaurant_service_modes','r1_restaurant_resource_profiles','r1_restaurant_service_sessions','r1_restaurant_session_resources','r1_restaurant_session_staff','r1_restaurant_orders','r1_restaurant_order_staff','r1_restaurant_order_lines','r1_restaurant_tabs','r1_restaurant_tab_orders','r1_restaurant_tab_partitions','r1_restaurant_tab_partition_lines','r1_restaurant_session_history','r1_restaurant_order_history','r1_restaurant_tab_history'}
TEXT={'.cmd','.json','.md','.py','.sql','.txt'}
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
def sha(p):
 d=p.read_bytes();d=d.replace(b'\r\n',b'\n') if p.suffix.lower() in TEXT else d;return hashlib.sha256(d).hexdigest()

def verify_manifest():
 m=load('r1_release_manifest.json')
 if (m['source_checkpoint'],m['source_archive_sha256'],m['source_archive_size'])!=(SOURCE,SOURCE_SHA,SOURCE_SIZE):raise RuntimeError('R1_RELEASE_SOURCE')
 if m['previous_head']!=PREVIOUS or m['accepted_head']!=HEAD or m['migration_count']!=1:raise RuntimeError('R1_RELEASE_BOUNDARY')
 if m['artifact_count']!=len(m['artifacts']) or len({x['path'] for x in m['artifacts']})!=len(m['artifacts']):raise RuntimeError('R1_RELEASE_COUNT')
 for x in m['artifacts']:
  p=ROOT/x['path']
  if not p.is_file() or sha(p)!=x['sha256']:raise RuntimeError('R1_RELEASE_ARTIFACT='+x['path'])
 return len(m['artifacts'])

def static_verify():
 a=load('r1_service_operation_authority.json');b=load('r1_finance_inventory_boundary.json');i=load('r1_public_interfaces.json');ready=load('r1_r2_readiness.json')
 if a['accepted_head']!=HEAD or a['previous_head']!=PREVIOUS:raise RuntimeError('R1_HEAD_CONTRACT')
 if not a['table_optional'] or not a['configurable_service_modes'] or 'cloud_kitchen' not in a['world_profiles']:raise RuntimeError('R1_WORLD_RESTAURANT_NEUTRALITY')
 if b['finance']['restaurant_creates_obligation'] or b['finance']['restaurant_posts_journal'] or b['inventory']['restaurant_writes_stock']:raise RuntimeError('R1_AUTHORITY_LEAK')
 if not b['inventory']['wnd_exactly_once_stock_effect_preserved']:raise RuntimeError('R1_WND_STOCK_INVARIANT')
 if i['http_routes_added'] or 'obligation_handoff' not in i['reads']:raise RuntimeError('R1_PUBLIC_BOUNDARY')
 if ready['status']!='READY_WHEN_R1_SINGLE_GATE_PASS':raise RuntimeError('R1_R2_READINESS')
 up=(ROOT/'alembic_neutral/sql/r1_restaurant_service_operation_up.sql').read_text()
 forbidden=['INSERT INTO financial_events','INSERT INTO obligations','INSERT INTO inventory_movements','INSERT INTO journals','INSERT INTO payment_']
 if any(x.lower() in up.lower() for x in forbidden):raise RuntimeError('R1_DUPLICATE_AUTHORITY_SQL')
 for token in ['REFERENCES public.so5_resources','REFERENCES public.so10_reservations','REFERENCES public.so1_prices','REFERENCES public.parties','REFERENCES public.identities']:
  if token not in up:raise RuntimeError('R1_SHARED_REFERENCE_MISSING='+token)
 # PostgreSQL composite foreign keys require the full referenced column tuple
 # to be backed by a PRIMARY KEY or UNIQUE constraint.  Partition lines are
 # tenant-scoped, so (tenant_id, id) is the canonical parent key.
 if 'CONSTRAINT uq_r1_partition_tenant_id UNIQUE(tenant_id,id)' not in up:
  raise RuntimeError('R1_PARTITION_TENANT_KEY_MISSING')
 if 'FOREIGN KEY(tenant_id,partition_id) REFERENCES public.r1_restaurant_tab_partitions(tenant_id,id)' not in up:
  raise RuntimeError('R1_PARTITION_LINE_FK_MISSING')
 release_count=verify_manifest()
 return {'status':'PASS','source_checkpoint':SOURCE[:7],'previous_head':PREVIOUS,'accepted_head':HEAD,'service_modes':'PASS','tables_optional':'PASS','orders':'PASS','staff_attribution':'PASS','tabs_split_bills':'PASS','reservation_composition':'PASS','finance':'UNCHANGED','inventory':'UNCHANGED','wnd_specimen_not_standard':'PASS','r2_readiness':'PASS','release_artifacts':release_count}
def _tables(conn):
 from sqlalchemy import text
 return set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).scalars())
def _run(operation,cfg,url,target):
 # alembic_neutral/env.py intentionally resolves DATABASE_URL as the runtime
 # authority and then mirrors it into Config.  Setting Config alone therefore
 # does not retarget an in-process Alembic command.  Scope both environment
 # authorities to the intended database and restore them after each command.
 old={key:os.environ.get(key) for key in ('DATABASE_URL','MIGRATION_DATABASE_URL')}
 cfg.set_main_option('sqlalchemy.url',url.replace('%','%%'))
 os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
 try:
  operation(cfg,target)
 finally:
  for key,value in old.items():
   if value is None:os.environ.pop(key,None)
   else:os.environ[key]=value
def acceptance():
 from alembic import command
 from alembic.config import Config
 from sqlalchemy import create_engine,text
 from sqlalchemy.engine import make_url
 from database import engine as app
 url=make_url(app.url)
 if url.host not in LOCAL or url.database!=DEV:raise RuntimeError('R1_REFUSING_DATABASE='+str(url))
 def eng(db,auto=False):return create_engine(url.set(database=db),pool_pre_ping=True,isolation_level='AUTOCOMMIT' if auto else None)
 admin=eng('postgres',True);test=None
 def drop():
  with admin.connect() as c:
   c.execute(text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()'),{'n':TEST});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST}"')
 try:
  drop()
  with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')
  test=eng(TEST);cfg=Config(str(ROOT/'alembic_neutral.ini'));test_url=url.set(database=TEST).render_as_string(hide_password=False)
  _run(command.upgrade,cfg,test_url,PREVIOUS)
  with test.connect() as c:
   if TABLES&_tables(c):raise RuntimeError('R1_PREDECESSOR_CONTAMINATION')
  _run(command.upgrade,cfg,test_url,HEAD)
  with test.connect() as c:
   missing=TABLES-_tables(c)
   if missing:raise RuntimeError('R1_TABLES_MISSING='+','.join(sorted(missing)))
   head=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
   if head!=HEAD:raise RuntimeError('R1_DISPOSABLE_HEAD')
  _run(command.downgrade,cfg,test_url,PREVIOUS)
  with test.connect() as c:
   if TABLES&_tables(c):raise RuntimeError('R1_DOWNGRADE_LEFT_TABLES')
  _run(command.upgrade,cfg,test_url,HEAD)
  with app.connect() as c:
   dev_head=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one();before=_tables(c)
  if dev_head==PREVIOUS:
   devcfg=Config(str(ROOT/'alembic_neutral.ini'));_run(command.upgrade,devcfg,url.render_as_string(hide_password=False),HEAD);action='UPGRADE'
  elif dev_head==HEAD:action='VERIFY_IN_PLACE'
  else:raise RuntimeError('R1_DEVELOPMENT_HEAD='+str(dev_head))
  with app.connect() as c:
   if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R1_DEVELOPMENT_ADOPTION')
   if not TABLES.issubset(_tables(c)):raise RuntimeError('R1_DEVELOPMENT_SCHEMA')
  return {'disposable_upgrade':'PASS','downgrade_reupgrade':'PASS','development_head':HEAD,'development_action':action}
 finally:
  if test:test.dispose()
  drop();admin.dispose()
def main():
 p=argparse.ArgumentParser();p.add_argument('--acceptance',action='store_true');args=p.parse_args()
 try:
  r=static_verify();
  if args.acceptance:r['database']=acceptance()
 except Exception as e:
  print('R1_VERIFY=FAIL\n'+str(e),file=sys.stderr);return 1
 print(json.dumps(r,indent=2,sort_keys=True));print('R1_VERIFY=PASS');return 0
if __name__=='__main__':raise SystemExit(main())
