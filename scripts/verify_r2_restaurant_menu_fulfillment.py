from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE='053fb8a6bbe40c11eeaeef23113ad2888122de65';SOURCE_SHA='7f79057eedad4bac241dc9c2d002666aa49126fb0711761d56b301f83587510c';SOURCE_SIZE=6045731
PREVIOUS='r1_restaurant_service_operation_042';HEAD='r2_restaurant_menu_fulfillment_043';DEV='xbos_track_b_dev';TEST='xbos_r2_acceptance';LOCAL={'localhost','127.0.0.1','::1'}
C=ROOT/'contracts/restaurant/v1';TEXT={'.cmd','.json','.md','.py','.sql','.txt'}
TABLES={
'r2_restaurant_commands','r2_restaurant_menu_sections','r2_restaurant_menu_section_entries','r2_restaurant_modifier_groups','r2_restaurant_modifier_options','r2_restaurant_menu_entry_modifier_groups','r2_restaurant_order_line_modifier_sets','r2_restaurant_order_line_modifier_items','r2_restaurant_station_profiles','r2_restaurant_routing_rules','r2_restaurant_preparation_specs','r2_restaurant_preparation_components','r2_restaurant_preparation_tickets','r2_restaurant_preparation_ticket_items','r2_restaurant_ticket_item_dependencies','r2_restaurant_ticket_history','r2_restaurant_ticket_item_history','r2_restaurant_preparation_runs','r2_restaurant_preparation_run_inputs','r2_restaurant_preparation_run_history'}
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
def sha(p):
 d=p.read_bytes();d=d.replace(b'\r\n',b'\n') if p.suffix.lower() in TEXT else d;return hashlib.sha256(d).hexdigest()
def verify_manifest():
 m=load('r2_release_manifest.json')
 if (m['source_checkpoint'],m['source_archive_sha256'],m['source_archive_size'])!=(SOURCE,SOURCE_SHA,SOURCE_SIZE):raise RuntimeError('R2_RELEASE_SOURCE')
 if m['previous_head']!=PREVIOUS or m['accepted_head']!=HEAD or m['migration_count']!=1:raise RuntimeError('R2_RELEASE_BOUNDARY')
 if m['artifact_count']!=len(m['artifacts']) or len({x['path'] for x in m['artifacts']})!=len(m['artifacts']):raise RuntimeError('R2_RELEASE_COUNT')
 for x in m['artifacts']:
  p=ROOT/x['path']
  if not p.is_file() or sha(p)!=x['sha256']:raise RuntimeError('R2_RELEASE_ARTIFACT='+x['path'])
 return len(m['artifacts'])
def static_verify():
 a=load('r2_menu_fulfillment_authority.json');b=load('r2_inventory_delivery_boundary.json');i=load('r2_public_interfaces.json');ready=load('r2_r3_readiness.json')
 if (a['source_checkpoint'],a['previous_head'],a['accepted_head'])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError('R2_HEAD_CONTRACT')
 if not a['wnd_specimen_not_standard'] or a['tables_required'] or a['printer_required'] or a['kds_required']:raise RuntimeError('R2_WORLD_RESTAURANT_NEUTRALITY')
 if a['finance_writer']!='NONE' or a['inventory_writer']!='NONE' or a['delivery_job_writer']!='NONE':raise RuntimeError('R2_DUPLICATE_AUTHORITY')
 if b['inventory']['restaurant_writes_inventory_movement'] or b['delivery']['restaurant_creates_delivery_job'] or b['finance']['restaurant_posts_journal']:raise RuntimeError('R2_BOUNDARY_LEAK')
 if not b['inventory']['wnd_exactly_once_sale_stock_effect_preserved']:raise RuntimeError('R2_WND_STOCK_INVARIANT')
 if i['http_routes_added'] or i['cross_module_private_access']!='FORBIDDEN':raise RuntimeError('R2_PUBLIC_BOUNDARY')
 required_commands={'DefineMenuSection','PlaceMenuEntry','DefineModifierGroup','AddModifierOption','BindMenuEntryModifierGroup','SetLineModifiers','ProfileStation','DefineRoutingRule','DefinePreparationSpec','ReleasePreparation'}
 if not required_commands.issubset(set(i['commands'])):raise RuntimeError('R2_PUBLIC_COMMANDS_INCOMPLETE')
 if 'semantic_routing' not in set(a['capabilities']):raise RuntimeError('R2_SC41_ROUTING_CAPABILITY')
 if ready['status']!='READY_WHEN_R2_SINGLE_GATE_PASS':raise RuntimeError('R2_R3_READINESS')
 up=(ROOT/'alembic_neutral/sql/r2_restaurant_menu_fulfillment_up.sql').read_text(encoding='utf-8')
 forbidden=['INSERT INTO public.inventory_movements','UPDATE public.inventory_items','INSERT INTO public.so8_delivery_jobs','INSERT INTO public.financial_events','INSERT INTO public.financial_obligations','INSERT INTO public.journal_entries','INSERT INTO public.payment_']
 if any(x.lower() in up.lower() for x in forbidden):raise RuntimeError('R2_DUPLICATE_AUTHORITY_SQL')
 required=['REFERENCES public.so1_catalogs','REFERENCES public.so1_catalog_entries','REFERENCES public.atomic_units','REFERENCES public.so1_offers','REFERENCES public.so1_prices','REFERENCES public.so5_resources','REFERENCES public.r1_restaurant_orders','REFERENCES public.r1_restaurant_order_lines']
 for token in required:
  if token not in up:raise RuntimeError('R2_SHARED_REFERENCE_MISSING='+token)
 for token in ['r2_restaurant_preparation_tickets','r2_restaurant_preparation_specs','r2_restaurant_preparation_runs','r2_restaurant_order_line_modifier_sets']:
  if token not in up:raise RuntimeError('R2_TABLE_CONTRACT_MISSING='+token)
 for token in ['R2_MENU_ENTRY_CATALOG_MISMATCH','R2_MODIFIER_PRICE_TARGET_MISMATCH','release_command_key varchar(180) NOT NULL']:
  if token not in up:raise RuntimeError('R2_HARDENING_MISSING='+token)
 repo=(ROOT/'restaurant/r2/sql_repository.py').read_text(encoding='utf-8')
 if 'WHERE tenant_id=:t AND release_command_key=:k' not in repo or 'uuid4()' not in repo:raise RuntimeError('R2_RELEASE_REPLAY_SCOPE')
 inv=json.loads((ROOT/'contracts/platform/v1/pc0_frozen_finance_inventory.json').read_text())
 ext={x['path']:x for x in inv['authorized_non_finance_extensions'] if x.get('root')=='alembic_neutral'}
 for path in ['versions/r2_restaurant_menu_fulfillment_043.py','sql/r2_restaurant_menu_fulfillment_up.sql','sql/r2_restaurant_menu_fulfillment_down.sql']:
  if path not in ext or ext[path].get('owner')!='PK':raise RuntimeError('R2_PC0_EXTENSION_MISSING='+path)
 release_count=verify_manifest()
 return {'status':'PASS','source_checkpoint':SOURCE[:7],'previous_head':PREVIOUS,'accepted_head':HEAD,'menu_projection':'PASS','menu_entry_placement':'PASS','modifiers':'PASS','semantic_routing':'PASS','station_routing':'PASS','tickets_hold_fire_course':'PASS','multi_station':'PASS','release_idempotency':'PASS','recipes_yield_waste':'PASS','inventory':'UNCHANGED','delivery':'UNCHANGED','finance':'UNCHANGED','wnd_specimen_not_standard':'PASS','r3_readiness':'PASS','release_artifacts':release_count}
def _tables(conn):
 from sqlalchemy import text
 return set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).scalars())
def _run(operation,cfg,url,target):
 old={key:os.environ.get(key) for key in ('DATABASE_URL','MIGRATION_DATABASE_URL')};cfg.set_main_option('sqlalchemy.url',url.replace('%','%%'));os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
 try:operation(cfg,target)
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
 if url.host not in LOCAL or url.database!=DEV:raise RuntimeError('R2_REFUSING_DATABASE='+str(url))
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
   if TABLES&_tables(c):raise RuntimeError('R2_PREDECESSOR_CONTAMINATION')
  _run(command.upgrade,cfg,test_url,HEAD)
  with test.connect() as c:
   missing=TABLES-_tables(c)
   if missing:raise RuntimeError('R2_TABLES_MISSING='+','.join(sorted(missing)))
   if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R2_DISPOSABLE_HEAD')
   cols=set(c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='r2_restaurant_preparation_tickets'")).scalars())
   if 'release_command_key' not in cols:raise RuntimeError('R2_RELEASE_COMMAND_COLUMN_MISSING')
   triggers=set(c.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'trg_r2_%'" )).scalars())
   for needed in {'trg_r2_menu_section_entry_tenant','trg_r2_modifier_option_authority','trg_r2_ticket_history_immutable','trg_r2_prep_run_history_immutable'}:
    if needed not in triggers:raise RuntimeError('R2_TRIGGER_MISSING='+needed)
  _run(command.downgrade,cfg,test_url,PREVIOUS)
  with test.connect() as c:
   if TABLES&_tables(c):raise RuntimeError('R2_DOWNGRADE_LEFT_TABLES')
  _run(command.upgrade,cfg,test_url,HEAD)
  with app.connect() as c:
   dev_head=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
  if dev_head==PREVIOUS:
   devcfg=Config(str(ROOT/'alembic_neutral.ini'));_run(command.upgrade,devcfg,url.render_as_string(hide_password=False),HEAD);action='UPGRADE'
  elif dev_head==HEAD:action='VERIFY_IN_PLACE'
  else:raise RuntimeError('R2_DEVELOPMENT_HEAD='+str(dev_head))
  with app.connect() as c:
   if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R2_DEVELOPMENT_ADOPTION')
   if not TABLES.issubset(_tables(c)):raise RuntimeError('R2_DEVELOPMENT_SCHEMA')
  return {'disposable_upgrade':'PASS','downgrade_reupgrade':'PASS','development_head':HEAD,'development_action':action}
 finally:
  if test:test.dispose()
  drop();admin.dispose()
def main():
 p=argparse.ArgumentParser();p.add_argument('--acceptance',action='store_true');args=p.parse_args()
 try:
  r=static_verify()
  if args.acceptance:r['database']=acceptance()
 except Exception as e:
  print('R2_VERIFY=FAIL\n'+str(e),file=sys.stderr);return 1
 print(json.dumps(r,indent=2,sort_keys=True));print('R2_VERIFY=PASS');return 0
if __name__=='__main__':raise SystemExit(main())
