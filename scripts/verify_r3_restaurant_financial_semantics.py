from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE='c9ab012e8e666f2bf96b8ad50b571f608acfeebd';SOURCE_SHA='5790bd3c1d5d345614ad092dfc87b5ecd63b67f9b9ff3ee5c3a7e544a21b7340';SOURCE_SIZE=6086967;HEAD='r2_restaurant_menu_fulfillment_043'
C=ROOT/'contracts/restaurant/v1';TEXT={'.cmd','.json','.md','.py','.sql','.txt'}
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
def sha(p):
 d=p.read_bytes();d=d.replace(b'\r\n',b'\n') if p.suffix.lower() in TEXT else d;return hashlib.sha256(d).hexdigest()
def verify_manifest():
 m=load('r3_release_manifest.json')
 if (m['source_checkpoint'],m['source_archive_sha256'],m['source_archive_size'])!=(SOURCE,SOURCE_SHA,SOURCE_SIZE):raise RuntimeError('R3_RELEASE_SOURCE')
 if m['previous_head']!=HEAD or m['accepted_head']!=HEAD or m['migration_count']!=0:raise RuntimeError('R3_RELEASE_BOUNDARY')
 if m['artifact_count']!=len(m['artifacts']) or len({x['path'] for x in m['artifacts']})!=len(m['artifacts']):raise RuntimeError('R3_RELEASE_COUNT')
 for x in m['artifacts']:
  p=ROOT/x['path']
  if not p.is_file() or sha(p)!=x['sha256']:raise RuntimeError('R3_RELEASE_ARTIFACT='+x['path'])
 return len(m['artifacts'])
def static_verify():
 a=load('r3_financial_semantics_authority.json');b=load('r3_finance_boundary.json');i=load('r3_public_interfaces.json');ready=load('r3_r4_readiness.json')
 if (a['source_checkpoint'],a['previous_head'],a['accepted_head'],a['migration'])!=(SOURCE,HEAD,HEAD,'NONE'):raise RuntimeError('R3_HEAD_CONTRACT')
 if any(a[x]!='NONE' for x in ('finance_writer','payment_writer','journal_writer','receivable_writer','report_ledger')):raise RuntimeError('R3_DUPLICATE_FINANCE_AUTHORITY')
 if a['r3_tables'] or a['database_change']!='NONE' or not a['wnd_specimen_not_standard']:raise RuntimeError('R3_DATABASE_OR_WND_BOUNDARY')
 if b['handoff']['creates_financial_truth'] or b['handoff']['executes_finance_commands'] or b['handoff']['writer_routing']!='unchanged':raise RuntimeError('R3_HANDOFF_WRITER_LEAK')
 if i['http_routes_added'] or i['cross_module_private_access']!='FORBIDDEN' or i['finance_execution']!='FORBIDDEN':raise RuntimeError('R3_PUBLIC_BOUNDARY')
 if ready['status']!='READY_WHEN_R3_SINGLE_GATE_PASS':raise RuntimeError('R3_R4_READINESS')
 source=(ROOT/'restaurant/r3/service.py').read_text(encoding='utf-8')
 forbidden=['finance.repository','_repository import','_engine import','session.execute','engine.begin','INSERT INTO','UPDATE public.financial','DELETE FROM public.financial']
 if any(x.lower() in source.lower() for x in forbidden):raise RuntimeError('R3_FINANCE_EXECUTION_LEAK')
 required=['COMMERCIAL_REVENUE_RECOGNIZED','RecognizeCommercialTermsCommand','CreateObligationCommand','RecognizeTipCommand','RecognizeCommissionCommand','RecognizeRefundCommand','ReverseFinancialFactCommand']
 for token in required:
  if token not in source:raise RuntimeError('R3_MAPPING_MISSING='+token)
 return verify_manifest()
def development_verify():
 from sqlalchemy import inspect,text
 from database import engine
 with engine.connect() as c:
  db=c.execute(text('select current_database()')).scalar_one();head=c.execute(text('select version_num from alembic_version')).scalar_one()
  names={x for x in inspect(c).get_table_names(schema='public') if x.startswith('r3_')}
 if head!=HEAD:raise RuntimeError(f'R3_DEVELOPMENT_HEAD={head}')
 if names:raise RuntimeError('R3_TABLES_FORBIDDEN='+','.join(sorted(names)))
 print(f'R3_DEVELOPMENT_DATABASE={db}');print(f'R3_DEVELOPMENT_HEAD={head}');print('R3_DEVELOPMENT_READ_ONLY=PASS')
def main():
 p=argparse.ArgumentParser();p.add_argument('--development',action='store_true');a=p.parse_args()
 count=static_verify()
 print(json.dumps({'accepted_head':HEAD,'database_change':'NONE','finance':'UNCHANGED','mapping_plan_only':'PASS','release_artifacts':count,'source_checkpoint':SOURCE[:7],'status':'PASS','wnd_specimen_not_standard':'PASS'},indent=2,sort_keys=True))
 print('R3_VERIFY=PASS')
 if a.development:development_verify()
if __name__=='__main__':
 try:main()
 except Exception as e:
  print('R3_VERIFY=FAIL');print(e);raise SystemExit(1)
