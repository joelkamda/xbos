from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace
import pytest

from shared_operations.so7 import (ChangeDocumentStatus,CreateDocument,DocumentStatus,EndEvidenceLink,EvidenceStatus,
    LinkEvidence,RegisterFileVersion,SO7Authority,SO7AuthorityError)
from shared_operations.so7.contracts import Document,DocumentVersion,EvidenceLink,SearchHit

ROOT=Path(__file__).resolve().parents[2]
NOW=datetime(2026,8,14,12,0,tzinfo=timezone.utc)
D=UUID(int=7001);V1=UUID(int=7002);V2=UUID(int=7003);E=UUID(int=7004)

class FakeRepo:
    def __init__(self):self.documents={};self.versions_by_id={};self.evidence_by_id={};self.commands={}
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old and old[:2]!=(fp,kind):raise SO7AuthorityError('SO7_COMMAND_CONFLICT','idempotency_conflict','conflict')
        return old
    def create_document(self,c,p,fp):
        old=self._cmd(c,fp,'create_document')
        if old:return self.documents[old[2]]
        v=Document(p,c.tenant_id,c.title,c.classification_code,DocumentStatus.ACTIVE,0,c.metadata,1);self.documents[p]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,'create_document',p);return v
    def document(self,t,p):
        v=self.documents.get(p);return v if v and v.tenant_id==t else None
    def list_documents(self,t,status=None,classification_code=None):
        return tuple(v for v in self.documents.values() if v.tenant_id==t and (status is None or v.status==status) and (classification_code is None or v.classification_code==classification_code))
    def register_version(self,c,p,fp):
        old=self._cmd(c,fp,'register_version')
        if old:return self.versions_by_id[old[2]]
        d=self.document(c.tenant_id,c.document_public_id)
        if not d or d.row_version!=c.expected_document_version or d.status is not DocumentStatus.ACTIVE:return None
        v=DocumentVersion(p,c.tenant_id,d.public_id,d.current_version_number+1,c.file_name,c.content_type,c.content_length,c.content_sha256,c.storage_provider,c.storage_key,c.created_by_reference,NOW)
        self.versions_by_id[p]=v;self.documents[d.public_id]=replace(d,current_version_number=v.version_number,row_version=d.row_version+1);self.commands[(c.tenant_id,c.command_key)]=(fp,'register_version',p);return v
    def version(self,t,p):
        v=self.versions_by_id.get(p);return v if v and v.tenant_id==t else None
    def versions(self,t,d):return tuple(sorted((v for v in self.versions_by_id.values() if v.tenant_id==t and v.document_public_id==d),key=lambda v:v.version_number))
    def current_version(self,t,d):
        doc=self.document(t,d)
        if not doc or doc.current_version_number<1:return None
        return next((v for v in self.versions(t,d) if v.version_number==doc.current_version_number),None)
    def link_evidence(self,c,p,fp):
        old=self._cmd(c,fp,'link_evidence')
        if old:return self.evidence_by_id[old[2]]
        d=self.document(c.tenant_id,c.document_public_id)
        if not d or d.row_version!=c.expected_document_version or d.status is DocumentStatus.WITHDRAWN:return None
        v=self.version(c.tenant_id,c.version_public_id) if c.version_public_id else self.current_version(c.tenant_id,d.public_id)
        if not v or v.document_public_id!=d.public_id:return None
        if any(x.tenant_id==c.tenant_id and x.document_public_id==d.public_id and x.version_public_id==v.public_id and x.subject_authority==c.subject_authority and x.subject_reference==c.subject_reference and x.relation_code==c.relation_code and x.status is EvidenceStatus.ACTIVE for x in self.evidence_by_id.values()):return None
        e=EvidenceLink(p,c.tenant_id,d.public_id,v.public_id,c.subject_authority,c.subject_reference,c.relation_code,EvidenceStatus.ACTIVE,None,None,1);self.evidence_by_id[p]=e;self.commands[(c.tenant_id,c.command_key)]=(fp,'link_evidence',p);return e
    def evidence(self,t,p):
        e=self.evidence_by_id.get(p);return e if e and e.tenant_id==t else None
    def evidence_for_subject(self,t,a,r,include_history=False):return tuple(e for e in self.evidence_by_id.values() if e.tenant_id==t and e.subject_authority==a and e.subject_reference==r and (include_history or e.status is EvidenceStatus.ACTIVE))
    def end_evidence(self,c,fp):
        old=self._cmd(c,fp,'end_evidence')
        if old:return self.evidence_by_id[old[2]]
        e=self.evidence(c.tenant_id,c.link_public_id)
        if not e or e.row_version!=c.expected_version or e.status is not EvidenceStatus.ACTIVE:return None
        e=replace(e,status=EvidenceStatus.ENDED,ended_at=c.occurred_at,end_reason_code=c.reason_code,row_version=e.row_version+1);self.evidence_by_id[e.public_id]=e;self.commands[(c.tenant_id,c.command_key)]=(fp,'end_evidence',e.public_id);return e
    def change_status(self,c,fp):
        old=self._cmd(c,fp,'change_status')
        if old:return self.documents[old[2]]
        d=self.document(c.tenant_id,c.document_public_id)
        if not d or d.row_version!=c.expected_version:return None
        d=replace(d,status=c.to_status,row_version=d.row_version+1);self.documents[d.public_id]=d;self.commands[(c.tenant_id,c.command_key)]=(fp,'change_status',d.public_id);return d
    def search(self,t,query=None,classification_code=None,status=None,limit=50):
        out=[]
        for d in self.list_documents(t,status,classification_code):
            v=self.current_version(t,d.public_id);hay=' '.join((d.title,d.classification_code,v.file_name if v else '')).lower()
            if query and query.lower() not in hay:continue
            out.append(SearchHit(d.public_id,d.title,d.classification_code,d.status,d.current_version_number,v.public_id if v else None,v.file_name if v else None,v.content_type if v else None))
        return tuple(out[:limit])

def authority(ids=None,permit=True,subjects=None):
    repo=FakeRepo();ids=iter(ids or [D,V1,V2,E,UUID(int=7005),UUID(int=7006)])
    subjects=subjects or {(1,'workflow','WF-1')}
    return SO7Authority(repo,classification_resolver=lambda t,c:c in {'inspection_report','clinical_certificate'},subject_resolver=lambda t,a,r:(t,a,r) in subjects,authorize=lambda *x:permit,public_id_factory=lambda:next(ids)),repo

def version_cmd(key,doc,row,sha='a'*64,name='report.pdf'):
    return RegisterFileVersion(key,1,doc,row,name,'application/pdf',128,sha,'local','evidence/'+name,'identity:42')

def test_document_identity_pc3_classification_and_exact_command_replay():
    so7,repo=authority();cmd=CreateDocument('doc-1',1,'Inspection Report','inspection_report',{'source':'field'})
    d=so7.create_document(cmd);assert d.public_id==D and d.classification_code=='inspection_report' and so7.create_document(cmd)==d and len(repo.documents)==1
    with pytest.raises(SO7AuthorityError,match='SO7_COMMAND_CONFLICT'):so7.create_document(replace(cmd,title='Changed'))
    with pytest.raises(SO7AuthorityError,match='SO7_CLASSIFICATION_NOT_FOUND'):so7.create_document(CreateDocument('bad',1,'Bad','restaurant_special'))

def test_file_versions_are_append_only_identity_and_current_version_is_explicit():
    so7,_=authority();d=so7.create_document(CreateDocument('d',1,'Report','inspection_report'))
    v1=so7.register_version(version_cmd('v1',d.public_id,d.row_version));d=so7.document(1,d.public_id)
    assert v1.version_number==1 and d.current_version_number==1 and so7.current_version(1,d.public_id)==v1
    v2=so7.register_version(version_cmd('v2',d.public_id,d.row_version,'b'*64,'report-v2.pdf'));assert v2.version_number==2
    assert [v.content_sha256 for v in so7.versions(1,d.public_id)]==['a'*64,'b'*64] and so7.current_version(1,d.public_id)==v2

def test_evidence_links_bind_exact_version_and_preserve_ended_history():
    so7,_=authority();d=so7.create_document(CreateDocument('d',1,'Report','inspection_report'));v=so7.register_version(version_cmd('v',d.public_id,d.row_version));d=so7.document(1,d.public_id)
    cmd=LinkEvidence('e',1,d.public_id,d.row_version,'workflow','WF-1','supporting_evidence')
    e=so7.link_evidence(cmd);assert e.version_public_id==v.public_id and so7.link_evidence(cmd)==e and len(so7.evidence_for_subject(1,'workflow','WF-1'))==1
    with pytest.raises(SO7AuthorityError,match='SO7_COMMAND_CONFLICT'):so7.link_evidence(replace(cmd,relation_code='alternate'))
    e=so7.end_evidence(EndEvidenceLink('end',1,e.public_id,e.row_version,'superseded',NOW));assert e.status is EvidenceStatus.ENDED and not so7.evidence_for_subject(1,'workflow','WF-1') and len(so7.evidence_for_subject(1,'workflow','WF-1',True))==1

def test_document_lifecycle_is_explicit_and_withdrawn_is_terminal():
    so7,_=authority();d=so7.create_document(CreateDocument('d',1,'Report','inspection_report'));d=so7.change_status(ChangeDocumentStatus('a',1,d.public_id,d.row_version,DocumentStatus.ARCHIVED,'inactive',NOW));assert d.status is DocumentStatus.ARCHIVED
    with pytest.raises(SO7AuthorityError,match='SO7_DOCUMENT_NOT_ACTIVE'):so7.register_version(version_cmd('v',d.public_id,d.row_version))
    d=so7.change_status(ChangeDocumentStatus('r',1,d.public_id,d.row_version,DocumentStatus.ACTIVE,'restored',NOW));d=so7.change_status(ChangeDocumentStatus('w',1,d.public_id,d.row_version,DocumentStatus.WITHDRAWN,'invalidated',NOW))
    with pytest.raises(SO7AuthorityError,match='SO7_INVALID_DOCUMENT_TRANSITION'):so7.change_status(ChangeDocumentStatus('back',1,d.public_id,d.row_version,DocumentStatus.ACTIVE,'restore',NOW))

def test_search_is_tenant_scoped_derived_discovery_not_source_of_truth():
    so7,_=authority();d=so7.create_document(CreateDocument('d',1,'Pump Inspection','inspection_report'));so7.register_version(version_cmd('v',d.public_id,d.row_version,name='pump.pdf'))
    hits=so7.search(1,'pump');assert len(hits)==1 and hits[0].document_public_id==d.public_id
    assert so7.document(1,hits[0].document_public_id).title=='Pump Inspection'
    assert so7.search(1,classification_code='inspection_report') and not so7.search(2,'pump')

def test_tenant_isolation_subject_validation_and_server_permission_fail_closed():
    so7,_=authority();d=so7.create_document(CreateDocument('d',1,'Report','inspection_report'));v=so7.register_version(version_cmd('v',d.public_id,d.row_version));d=so7.document(1,d.public_id)
    with pytest.raises(SO7AuthorityError,match='SO7_SUBJECT_NOT_FOUND'):so7.link_evidence(LinkEvidence('x',1,d.public_id,d.row_version,'workflow','FOREIGN','supporting',v.public_id))
    with pytest.raises(SO7AuthorityError,match='SO7_VERSION_SCOPE_MISMATCH'):so7.link_evidence(LinkEvidence('x2',1,d.public_id,d.row_version,'workflow','WF-1','supporting',UUID(int=999)))
    denied,_=authority(permit=False)
    with pytest.raises(SO7AuthorityError,match='SO7_PERMISSION_DENIED'):denied.list_documents(1)

def test_neutral_profiles_and_authority_boundaries_are_explicit():
    a=json.loads((ROOT/'contracts/shared_operations/v1/examples/field_service_evidence_profile.json').read_text());b=json.loads((ROOT/'contracts/shared_operations/v1/examples/clinical_document_profile.json').read_text());assert a['terminology']!=b['terminology'] and a['classifications']!=b['classifications']
    authority_contract=json.loads((ROOT/'contracts/shared_operations/v1/so7_authority.json').read_text());assert authority_contract['semantic_authority']=='PC3_REUSED' and authority_contract['security_authority']=='PC5_REUSED' and authority_contract['finance']=='UNCHANGED'

def test_sql_versions_are_immutable_search_is_derived_and_finance_writers_absent():
    sql=(ROOT/'alembic_neutral/sql/so7_documents_files_evidence_search_up.sql').read_text()
    assert 'so7_version_immutable' in sql and 'CREATE VIEW public.so7_document_search_projection' in sql
    assert 'UNIQUE(tenant_id,document_id,version_number)' in sql and 'REFERENCES public.so7_document_versions(tenant_id,document_id,id)' in sql
    low=sql.lower()
    for forbidden in ('financial_events','journal_entries','financial_obligations','payment_settlements','audit_evidence','protected_action_approvals'):assert forbidden not in low
    repo=(ROOT/'shared_operations/so7/sql_repository.py').read_text();assert 'FOR UPDATE OF d' in repo and 'FOR UPDATE OF e' in repo and 'so7_document_search_projection' in repo
