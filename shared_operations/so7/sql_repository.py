"""SQLAlchemy repository for SO7 documents, file versions, evidence links, and derived search."""
from __future__ import annotations
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO7AuthorityError

class SQLSO7Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so7_document_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO7AuthorityError("SO7_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so7_document_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so7_document_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _document_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF d" if lock else ""
        return self.db_session.execute(text("SELECT d.* FROM so7_documents d WHERE d.tenant_id=:t AND d.public_id=:p"+suffix),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _document(value):
        if not value:return None
        return Document(UUID(str(value.public_id)),value.tenant_id,value.title,value.classification_code,DocumentStatus(value.lifecycle_status),value.current_version_number,value.metadata,value.row_version)
    def create_document(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"create_document")
        if replay.result_public_id:return self.document(command.tenant_id,replay.result_public_id)
        self.db_session.execute(text("""INSERT INTO so7_documents(public_id,tenant_id,title,classification_code,lifecycle_status,metadata) VALUES(:p,:t,:title,:c,'active',CAST(:m AS jsonb))"""),{"p":str(public_id),"t":command.tenant_id,"title":command.title,"c":command.classification_code,"m":__import__('json').dumps(command.metadata,sort_keys=True)})
        self._complete(command.tenant_id,command.command_key,"document",public_id);return self.document(command.tenant_id,public_id)
    def document(self,tenant_id,public_id):return self._document(self._document_row(tenant_id,public_id))
    def list_documents(self,tenant_id,status=None,classification_code=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so7_documents WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) AND (:c IS NULL OR classification_code=:c) ORDER BY id"),{"t":tenant_id,"s":getattr(status,"value",status),"c":classification_code}).all()
        return tuple(self.document(tenant_id,UUID(str(r.public_id))) for r in rows)
    def _version_row(self,tenant,public_id):
        return self.db_session.execute(text("""SELECT v.*,d.public_id document_public_id FROM so7_document_versions v JOIN so7_documents d ON (d.tenant_id,d.id)=(v.tenant_id,v.document_id) WHERE v.tenant_id=:t AND v.public_id=:p"""),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _version(value):
        if not value:return None
        return DocumentVersion(UUID(str(value.public_id)),value.tenant_id,UUID(str(value.document_public_id)),value.version_number,value.file_name,value.content_type,value.content_length,value.content_sha256,value.storage_provider,value.storage_key,value.created_by_reference,value.created_at)
    def register_version(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"register_version")
        if replay.result_public_id:return self.version(command.tenant_id,replay.result_public_id)
        d=self._document_row(command.tenant_id,command.document_public_id,True)
        if not d or d.row_version!=command.expected_document_version or d.lifecycle_status!="active":return None
        number=d.current_version_number+1
        self.db_session.execute(text("""INSERT INTO so7_document_versions(public_id,tenant_id,document_id,version_number,file_name,content_type,content_length,content_sha256,storage_provider,storage_key,created_by_reference) VALUES(:p,:t,:d,:n,:f,:ct,:len,:sha,:sp,:sk,:actor)"""),{"p":str(public_id),"t":command.tenant_id,"d":d.id,"n":number,"f":command.file_name,"ct":command.content_type,"len":command.content_length,"sha":command.content_sha256,"sp":command.storage_provider,"sk":command.storage_key,"actor":command.created_by_reference})
        updated=self.db_session.execute(text("UPDATE so7_documents SET current_version_number=:n,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:d AND row_version=:v RETURNING row_version"),{"n":number,"t":command.tenant_id,"d":d.id,"v":command.expected_document_version}).first()
        if not updated:return None
        self._complete(command.tenant_id,command.command_key,"version",public_id);return self.version(command.tenant_id,public_id)
    def version(self,tenant_id,public_id):return self._version(self._version_row(tenant_id,public_id))
    def versions(self,tenant_id,document_public_id):
        d=self._document_row(tenant_id,document_public_id)
        if not d:return ()
        rows=self.db_session.execute(text("SELECT public_id FROM so7_document_versions WHERE tenant_id=:t AND document_id=:d ORDER BY version_number"),{"t":tenant_id,"d":d.id}).all()
        return tuple(self.version(tenant_id,UUID(str(r.public_id))) for r in rows)
    def current_version(self,tenant_id,document_public_id):
        d=self._document_row(tenant_id,document_public_id)
        if not d or not d.current_version_number:return None
        row=self.db_session.execute(text("SELECT public_id FROM so7_document_versions WHERE tenant_id=:t AND document_id=:d AND version_number=:n"),{"t":tenant_id,"d":d.id,"n":d.current_version_number}).first()
        return self.version(tenant_id,UUID(str(row.public_id))) if row else None
    def _evidence_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF e" if lock else ""
        return self.db_session.execute(text("""SELECT e.*,d.public_id document_public_id,v.public_id version_public_id FROM so7_evidence_links e JOIN so7_documents d ON (d.tenant_id,d.id)=(e.tenant_id,e.document_id) JOIN so7_document_versions v ON (v.tenant_id,v.document_id,v.id)=(e.tenant_id,e.document_id,e.version_id) WHERE e.tenant_id=:t AND e.public_id=:p"""+suffix),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _evidence(value):
        if not value:return None
        return EvidenceLink(UUID(str(value.public_id)),value.tenant_id,UUID(str(value.document_public_id)),UUID(str(value.version_public_id)),value.subject_authority,value.subject_reference,value.relation_code,EvidenceStatus(value.lifecycle_status),value.ended_at,value.end_reason_code,value.row_version)
    def link_evidence(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"link_evidence")
        if replay.result_public_id:return self.evidence(command.tenant_id,replay.result_public_id)
        d=self._document_row(command.tenant_id,command.document_public_id,True)
        if not d or d.row_version!=command.expected_document_version or d.lifecycle_status=="withdrawn" or d.current_version_number<1:return None
        if command.version_public_id:
            v=self.db_session.execute(text("SELECT id,public_id FROM so7_document_versions WHERE tenant_id=:t AND document_id=:d AND public_id=:p"),{"t":command.tenant_id,"d":d.id,"p":str(command.version_public_id)}).first()
        else:
            v=self.db_session.execute(text("SELECT id,public_id FROM so7_document_versions WHERE tenant_id=:t AND document_id=:d AND version_number=:n"),{"t":command.tenant_id,"d":d.id,"n":d.current_version_number}).first()
        if not v:return None
        duplicate=self.db_session.execute(text("""SELECT 1 FROM so7_evidence_links WHERE tenant_id=:t AND document_id=:d AND version_id=:v AND subject_authority=:sa AND subject_reference=:sr AND relation_code=:r AND lifecycle_status='active'"""),{"t":command.tenant_id,"d":d.id,"v":v.id,"sa":command.subject_authority,"sr":command.subject_reference,"r":command.relation_code}).scalar()
        if duplicate:return None
        self.db_session.execute(text("""INSERT INTO so7_evidence_links(public_id,tenant_id,document_id,version_id,subject_authority,subject_reference,relation_code,lifecycle_status) VALUES(:p,:t,:d,:v,:sa,:sr,:r,'active')"""),{"p":str(public_id),"t":command.tenant_id,"d":d.id,"v":v.id,"sa":command.subject_authority,"sr":command.subject_reference,"r":command.relation_code})
        self._complete(command.tenant_id,command.command_key,"evidence",public_id);return self.evidence(command.tenant_id,public_id)
    def evidence(self,tenant_id,public_id):return self._evidence(self._evidence_row(tenant_id,public_id))
    def evidence_for_subject(self,tenant_id,subject_authority,subject_reference,include_history=False):
        clause="" if include_history else " AND lifecycle_status='active'"
        rows=self.db_session.execute(text("SELECT public_id FROM so7_evidence_links WHERE tenant_id=:t AND subject_authority=:a AND subject_reference=:r"+clause+" ORDER BY id"),{"t":tenant_id,"a":subject_authority,"r":subject_reference}).all()
        return tuple(self.evidence(tenant_id,UUID(str(x.public_id))) for x in rows)
    def end_evidence(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"end_evidence")
        if replay.result_public_id:return self.evidence(command.tenant_id,replay.result_public_id)
        e=self._evidence_row(command.tenant_id,command.link_public_id,True)
        if not e or e.row_version!=command.expected_version or e.lifecycle_status!="active":return None
        updated=self.db_session.execute(text("""UPDATE so7_evidence_links SET lifecycle_status='ended',ended_at=:at,end_reason_code=:reason,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v AND lifecycle_status='active' RETURNING id"""),{"at":command.occurred_at,"reason":command.reason_code,"t":command.tenant_id,"id":e.id,"v":command.expected_version}).first()
        if not updated:return None
        self._complete(command.tenant_id,command.command_key,"evidence",command.link_public_id);return self.evidence(command.tenant_id,command.link_public_id)
    def change_status(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"change_status")
        if replay.result_public_id:return self.document(command.tenant_id,replay.result_public_id)
        d=self._document_row(command.tenant_id,command.document_public_id,True)
        if not d or d.row_version!=command.expected_version:return None
        updated=self.db_session.execute(text("UPDATE so7_documents SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING id"),{"s":command.to_status.value,"t":command.tenant_id,"id":d.id,"v":command.expected_version}).first()
        if not updated:return None
        self._complete(command.tenant_id,command.command_key,"document",command.document_public_id);return self.document(command.tenant_id,command.document_public_id)
    def search(self,tenant_id,query=None,classification_code=None,status=None,limit=50):
        pattern=f"%{query}%" if query else None
        rows=self.db_session.execute(text("""SELECT * FROM so7_document_search_projection WHERE tenant_id=:t AND (:q IS NULL OR title ILIKE :q OR COALESCE(current_file_name,'') ILIKE :q OR classification_code ILIKE :q) AND (:c IS NULL OR classification_code=:c) AND (:s IS NULL OR lifecycle_status=:s) ORDER BY title,document_public_id LIMIT :limit"""),{"t":tenant_id,"q":pattern,"c":classification_code,"s":getattr(status,"value",status),"limit":limit}).all()
        return tuple(SearchHit(UUID(str(r.document_public_id)),r.title,r.classification_code,DocumentStatus(r.lifecycle_status),r.current_version_number,UUID(str(r.current_version_public_id)) if r.current_version_public_id else None,r.current_file_name,r.current_content_type) for r in rows)
