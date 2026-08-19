from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE='64fa78ef9df34a263ebfff449839bbeca477aac7';SOURCE_SHA='5bc1b85479db5d45becb4555cdacf1c22a8683acf9588c4ab0578819484a1271';SOURCE_SIZE=6109884;HEAD='r2_restaurant_menu_fulfillment_043';DEV='xbos_track_b_dev';TEST='xbos_r4_acceptance';LOCAL={'localhost','127.0.0.1','::1'}
C=ROOT/'contracts/restaurant/v1';TEXT={'.cmd','.json','.md','.py','.sql','.txt'}
PACK_CODE='industry.restaurant';PACK_VERSION='1.0.0';CERT='restaurant.r4.conformance'
EVIDENCE_PATHS=(
 'contracts/restaurant/v1/r0_release_manifest.json','contracts/restaurant/v1/r1_release_manifest.json','contracts/restaurant/v1/r2_release_manifest.json','contracts/restaurant/v1/r3_release_manifest.json',
 'contracts/packs/v1/pk_aggregate_release_manifest.json','contracts/platform/v1/sc41_semantic_classification_hardening.json','contracts/experience/v1/xa_release_manifest.json')
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
def sha(p):
 d=p.read_bytes();d=d.replace(b'\r\n',b'\n') if p.suffix.lower() in TEXT else d;return hashlib.sha256(d).hexdigest()
def evidence_hashes():return tuple(sha(ROOT/p) for p in EVIDENCE_PATHS)
def verify_manifest():
 m=load('r4_release_manifest.json')
 if (m['source_checkpoint'],m['source_archive_sha256'],m['source_archive_size'])!=(SOURCE,SOURCE_SHA,SOURCE_SIZE):raise RuntimeError('R4_RELEASE_SOURCE')
 if m['previous_head']!=HEAD or m['accepted_head']!=HEAD or m['migration_count']!=0:raise RuntimeError('R4_RELEASE_BOUNDARY')
 if m['artifact_count']!=len(m['artifacts']) or len({x['path'] for x in m['artifacts']})!=len(m['artifacts']):raise RuntimeError('R4_RELEASE_COUNT')
 for x in m['artifacts']:
  p=ROOT/x['path']
  if not p.is_file() or sha(p)!=x['sha256']:raise RuntimeError('R4_RELEASE_ARTIFACT='+x['path'])
 return len(m['artifacts'])
def static_verify():
 from pack_platform import PackAuthority
 from pack_platform.pk456_service import PK456Authority
 from restaurant.r4 import build_registration_plan, build_restaurant_pack_manifest
 a=load('r4_pack_registration_authority.json');m=load('r4_restaurant_pack_manifest.json');s=load('r4_semantic_configuration_contributions.json');p=load('r4_pk_conformance.json');i=load('r4_public_interfaces.json');ready=load('r4_r5_readiness.json')
 if (a['source_checkpoint'],a['previous_head'],a['accepted_head'],a['migration'])!=(SOURCE,HEAD,HEAD,'NONE'):raise RuntimeError('R4_HEAD_CONTRACT')
 if a['registration']['tenant_installation'] or a['registration']['tenant_activation'] or a['registration']['template_registration'] or a['registration']['template_application'] or a['registration']['wnd_cutover']:raise RuntimeError('R4_SCOPE_LEAK')
 if a['database']['schema_change']!='NONE' or a['database']['r4_tables']:raise RuntimeError('R4_DATABASE_SCOPE')
 if not a['wnd_specimen_not_standard']:raise RuntimeError('R4_WND_STANDARD_LEAK')
 if m['pack_code']!=PACK_CODE or m['version']!=PACK_VERSION or m['kind']!='industry' or m['connectors']:raise RuntimeError('R4_MANIFEST_IDENTITY')
 if m['xa']['tables_required'] or m['xa']['frontend_implemented'] or m['xa']['composition_engine_implemented'] or m['xa']['wnd_profile_is_standard']:raise RuntimeError('R4_XA_NEUTRALITY')
 if s['semantic_contribution']['scope']!='pack' or s['semantic_contribution']['closed_value_sets'] or s['configuration']['industry_wide_hardcoded_defaults'] or s['configuration']['wnd_literals']:raise RuntimeError('R4_SEMANTIC_CONFIG_BOUNDARY')
 if p['tenant_installation']!='NONE' or p['template_application']!='NONE' or p['direct_pk_table_write'] or p['direct_finance_write'] or p['direct_shared_operations_write']:raise RuntimeError('R4_PK_BOUNDARY')
 if set(p['required_checks'])!={'architecture','tenant_isolation','migration_compatibility','authorization','semantics','finance','shared_operations','xa','manifest'}:raise RuntimeError('R4_CERT_CHECK_COVERAGE')
 if i['http_routes_added'] or i['cross_module_private_access']!='FORBIDDEN':raise RuntimeError('R4_PUBLIC_BOUNDARY')
 if ready['status']!='READY_WHEN_R4_SINGLE_GATE_PASS':raise RuntimeError('R4_R5_READINESS')
 manifest=build_restaurant_pack_manifest()
 if manifest.pack_code!=PACK_CODE or manifest.version!=PACK_VERSION or manifest.kind.value!='industry':raise RuntimeError('R4_RUNTIME_MANIFEST')
 if set(m['required_modules'])!=set(manifest.required_modules) or set(m['optional_modules'])!=set(manifest.optional_modules):raise RuntimeError('R4_MANIFEST_MODULE_DRIFT')
 if set(m['permission_references'])!=set(manifest.permission_references) or set(m['semantic_namespaces'])!=set(manifest.semantic_namespaces) or set(m['configuration_keys'])!=set(manifest.configuration_keys):raise RuntimeError('R4_MANIFEST_DECLARATION_DRIFT')
 if {x['extension_code'] for x in m['extensions']}!={x.extension_code for x in manifest.extensions}:raise RuntimeError('R4_MANIFEST_EXTENSION_DRIFT')
 source=(ROOT/'restaurant/r4/service.py').read_text(encoding='utf-8').lower()
 forbidden=('sql_repository','from database import','session.execute','insert into','update pk_','delete from')
 if any(token in source for token in forbidden):raise RuntimeError('R4_DIRECT_WRITER_OR_WND_LEAK')
 plan=build_registration_plan(evidence_hashes())
 if plan.tenant_installation_authorized or plan.template_application_authorized or plan.wnd_cutover_authorized:raise RuntimeError('R4_PLAN_SCOPE')
 class RegisterRepo:
  def register_version(self,key,fingerprint,manifest,canonical,h):
   from pack_platform.contracts import PackVersionRecord
   from uuid import UUID
   self.record=(key,fingerprint,manifest,canonical,h);return PackVersionRecord(UUID(int=1),manifest.pack_code,manifest.version,manifest.owner_code,manifest.kind,h,manifest.retention_required)
 rr=RegisterRepo();record=PackAuthority(rr).register(plan.register_command)
 if record.pack_code!=PACK_CODE or len(record.manifest_sha256)!=64:raise RuntimeError('R4_PK_REGISTER_CONTRACT')
 class CertRepo:
  def pack_version(self,code,version):return {'manifest_sha256':record.manifest_sha256} if (code,version)==(PACK_CODE,PACK_VERSION) else None
  def certify(self,*args):
   from pack_platform.pk456_contracts import PackCertificationRecord,ConformanceResult
   from uuid import UUID
   return PackCertificationRecord(UUID(int=2),PACK_CODE,PACK_VERSION,CERT,'1.0.0',record.manifest_sha256,args[7],ConformanceResult.PASS)
 cert=PK456Authority(CertRepo()).certify(plan.certification_command)
 if cert.result.value!='pass':raise RuntimeError('R4_PK_CERTIFICATION_CONTRACT')
 return {'status':'PASS','source_checkpoint':SOURCE[:7],'accepted_head':HEAD,'migration':'NONE','pack_code':PACK_CODE,'pack_version':PACK_VERSION,'pk_registration':'PASS','pk_certification':'PASS','semantic_contribution':'PASS','configuration_declarations':'PASS','xa_metadata':'PASS','tenant_installation':'NONE','template_application':'NONE','wnd_cutover':'NONE','r5_readiness':'PASS','release_artifacts':verify_manifest()}
def _register(session):
 from pack_platform import PackAuthority
 from pack_platform.sql_repository import SQLPackRepository
 from pack_platform.pk456_service import PK456Authority
 from pack_platform.pk456_sql_repository import SQLPK456Repository
 from restaurant.r4 import build_registration_plan
 plan=build_registration_plan(evidence_hashes())
 record=PackAuthority(SQLPackRepository(session)).register(plan.register_command)
 cert=PK456Authority(SQLPK456Repository(session)).certify(plan.certification_command)
 return record,cert
def _verify_registry(conn):
 from sqlalchemy import text
 row=conn.execute(text("""SELECT p.pack_code,p.owner_code,p.pack_kind,v.pack_version,v.manifest_sha256
 FROM pk_packs p JOIN pk_pack_versions v ON v.pack_id=p.id WHERE p.pack_code=:c AND v.pack_version=:v"""),{'c':PACK_CODE,'v':PACK_VERSION}).mappings().one_or_none()
 if not row or row['owner_code']!='restaurant' or row['pack_kind']!='industry':raise RuntimeError('R4_PACK_REGISTRATION_MISSING')
 cert=conn.execute(text("""SELECT c.result,c.certification_code,c.manifest_sha256 FROM pk_pack_certifications c
 JOIN pk_pack_versions v ON v.id=c.pack_version_id JOIN pk_packs p ON p.id=v.pack_id
 WHERE p.pack_code=:c AND v.pack_version=:v AND c.certification_code=:cc"""),{'c':PACK_CODE,'v':PACK_VERSION,'cc':CERT}).mappings().one_or_none()
 if not cert or cert['result']!='pass' or cert['manifest_sha256']!=row['manifest_sha256']:raise RuntimeError('R4_PACK_CERTIFICATION_MISSING')
 tenant_count=conn.execute(text("""SELECT count(*) FROM pk_tenant_pack_installations i JOIN pk_packs p ON p.id=i.pack_id WHERE p.pack_code=:c"""),{'c':PACK_CODE}).scalar_one()
 template_count=conn.execute(text("""SELECT count(*) FROM pk_template_pack_requirements WHERE pack_code=:c"""),{'c':PACK_CODE}).scalar_one()
 if tenant_count or template_count:raise RuntimeError(f'R4_TENANT_OR_TEMPLATE_SCOPE={tenant_count}:{template_count}')
 return row['manifest_sha256']
def acceptance():
 from alembic import command
 from alembic.config import Config
 from sqlalchemy import create_engine,text
 from sqlalchemy.engine import make_url
 from sqlalchemy.orm import Session
 from database import engine as app
 url=make_url(app.url)
 if url.host not in LOCAL or url.database!=DEV:raise RuntimeError('R4_REFUSING_DATABASE='+str(url))
 def eng(db,auto=False):return create_engine(url.set(database=db),pool_pre_ping=True,isolation_level='AUTOCOMMIT' if auto else None)
 def run(operation,cfg,target_url,target):
  old={k:os.environ.get(k) for k in ('DATABASE_URL','MIGRATION_DATABASE_URL')};cfg.set_main_option('sqlalchemy.url',target_url.replace('%','%%'));os.environ.update(DATABASE_URL=target_url,MIGRATION_DATABASE_URL=target_url)
  try:operation(cfg,target)
  finally:
   for k,v in old.items():
    if v is None:os.environ.pop(k,None)
    else:os.environ[k]=v
 admin=eng('postgres',True);test=None
 def drop():
  with admin.connect() as c:
   c.execute(text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()'),{'n':TEST});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST}"')
 try:
  drop()
  with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')
  test=eng(TEST);cfg=Config(str(ROOT/'alembic_neutral.ini'));target_url=url.set(database=TEST).render_as_string(hide_password=False);run(command.upgrade,cfg,target_url,HEAD)
  with Session(test) as s,s.begin():
   record,cert=_register(s)
   if record.pack_code!=PACK_CODE or cert.result.value!='pass':raise RuntimeError('R4_DISPOSABLE_REGISTER_CERT')
  with test.connect() as c:
   if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R4_DISPOSABLE_HEAD')
   manifest_sha=_verify_registry(c)
   r4tables=list(c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'r4_%'" )).scalars())
   if r4tables:raise RuntimeError('R4_TABLES_FORBIDDEN='+','.join(r4tables))
  return {'disposable_registration':'PASS','disposable_certification':'PASS','manifest_sha256':manifest_sha,'schema_head':HEAD,'tenant_installation':'NONE','template_application':'NONE'}
 finally:
  if test:test.dispose()
  drop();admin.dispose()
def adopt_development():
 from sqlalchemy import text
 from sqlalchemy.orm import Session
 from database import engine
 from sqlalchemy.engine import make_url
 url=make_url(engine.url)
 if url.host not in LOCAL or url.database!=DEV:raise RuntimeError('R4_REFUSING_DATABASE='+str(url))
 with engine.connect() as c:
  if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R4_DEVELOPMENT_HEAD')
 with Session(engine) as s,s.begin():_register(s)
 with engine.connect() as c:
  manifest_sha=_verify_registry(c)
  if c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()!=HEAD:raise RuntimeError('R4_DEVELOPMENT_HEAD_CHANGED')
  if list(c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'r4_%'" )).scalars()):raise RuntimeError('R4_DEVELOPMENT_TABLES_FORBIDDEN')
 print('R4_DEVELOPMENT_DATABASE='+DEV);print('R4_DEVELOPMENT_HEAD='+HEAD);print('R4_DEVELOPMENT_MANIFEST_SHA256='+manifest_sha);print('R4_DEVELOPMENT_PACK_REGISTERED=PASS');print('R4_DEVELOPMENT_PACK_CERTIFIED=PASS');print('R4_DEVELOPMENT_TENANT_INSTALLATION=NONE');print('R4_DEVELOPMENT_TEMPLATE_APPLICATION=NONE')
def main():
 p=argparse.ArgumentParser();p.add_argument('--acceptance',action='store_true');p.add_argument('--adopt-development',action='store_true');args=p.parse_args()
 try:
  r=static_verify()
  if args.acceptance:r['database']=acceptance()
  print(json.dumps(r,indent=2,sort_keys=True));print('R4_VERIFY=PASS')
  if args.adopt_development:adopt_development()
 except Exception as e:
  print('R4_VERIFY=FAIL');print(e);return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
