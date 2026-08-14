"""SO7 neutral document, file-version, evidence-link, and search authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class SO7AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable
        super().__init__(code)

class SO7Repository(Protocol):
    def create_document(self,command,public_id,fingerprint)->Document: ...
    def document(self,tenant_id,public_id)->Document|None: ...
    def list_documents(self,tenant_id,status=None,classification_code=None): ...
    def register_version(self,command,public_id,fingerprint)->DocumentVersion|None: ...
    def version(self,tenant_id,public_id)->DocumentVersion|None: ...
    def versions(self,tenant_id,document_public_id): ...
    def current_version(self,tenant_id,document_public_id)->DocumentVersion|None: ...
    def link_evidence(self,command,public_id,fingerprint)->EvidenceLink|None: ...
    def evidence(self,tenant_id,public_id)->EvidenceLink|None: ...
    def evidence_for_subject(self,tenant_id,subject_authority,subject_reference,include_history=False): ...
    def end_evidence(self,command,fingerprint)->EvidenceLink|None: ...
    def change_status(self,command,fingerprint)->Document|None: ...
    def search(self,tenant_id,query=None,classification_code=None,status=None,limit=50): ...

class SO7Authority:
    def __init__(self,repository:SO7Repository,*,classification_resolver:Callable,subject_resolver:Callable,
                 authorize:Callable,public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository;self.classification_resolver=classification_resolver;self.subject_resolver=subject_resolver
        self.authorize=authorize;self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command):return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
            raise SO7AuthorityError("SO7_INVALID_"+field.upper(),"validation_failure",field+" must be a neutral code")
        return value
    @staticmethod
    def _text(value,field,max_length=240):
        value=value.strip()
        if not value or len(value)>max_length:raise SO7AuthorityError("SO7_INVALID_"+field.upper(),"validation_failure",field+" is required and bounded")
        return value
    @staticmethod
    def _sha(value):
        value=value.strip().lower()
        if len(value)!=64 or any(c not in "0123456789abcdef" for c in value):raise SO7AuthorityError("SO7_INVALID_CONTENT_SHA256","validation_failure","content_sha256 must be lowercase SHA-256")
        return value
    def _permit(self,tenant,permission,scope_type="tenant",scope_id=None):
        if not self.authorize(tenant,permission,scope_type,tenant if scope_id is None else scope_id):
            raise SO7AuthorityError("SO7_PERMISSION_DENIED","permission_denied","The document operation is not permitted")
    def _classification(self,tenant,code):
        code=self._code(code,"classification_code")
        value=self.classification_resolver(tenant,code)
        if not value:raise SO7AuthorityError("SO7_CLASSIFICATION_NOT_FOUND","scope_mismatch","The PC3 document classification is not available in this tenant context")
        return code
    def _subject(self,tenant,authority,reference):
        authority=self._code(authority,"subject_authority");reference=self._text(reference,"subject_reference")
        if not self.subject_resolver(tenant,authority,reference):raise SO7AuthorityError("SO7_SUBJECT_NOT_FOUND","scope_mismatch","The evidence subject was not found in this tenant")
        return authority,reference
    def create_document(self,command:CreateDocument):
        self._permit(command.tenant_id,"document.create")
        normalized=replace(command,title=self._text(command.title,"title"),classification_code=self._classification(command.tenant_id,command.classification_code))
        if not isinstance(normalized.metadata,dict):raise SO7AuthorityError("SO7_INVALID_METADATA","validation_failure","metadata must be an object")
        return self.repository.create_document(normalized,self.public_id_factory(),self._fingerprint(normalized))
    def document(self,tenant_id,public_id):
        self._permit(tenant_id,"document.read","document",public_id);value=self.repository.document(tenant_id,public_id)
        if value is None:raise SO7AuthorityError("SO7_DOCUMENT_NOT_FOUND","not_found","The document was not found")
        return value
    def list_documents(self,tenant_id,status=None,classification_code=None):
        self._permit(tenant_id,"document.read")
        code=self._classification(tenant_id,classification_code) if classification_code else None
        return self.repository.list_documents(tenant_id,status,code)
    def register_version(self,command:RegisterFileVersion):
        self._permit(command.tenant_id,"document.version.create","document",command.document_public_id)
        current=self.repository.document(command.tenant_id,command.document_public_id)
        if current is None:raise SO7AuthorityError("SO7_DOCUMENT_NOT_FOUND","not_found","The document was not found")
        if current.status is not DocumentStatus.ACTIVE:raise SO7AuthorityError("SO7_DOCUMENT_NOT_ACTIVE","invalid_state_transition","New file versions require an active document")
        if command.content_length<0:raise SO7AuthorityError("SO7_INVALID_CONTENT_LENGTH","validation_failure","content_length must be non-negative")
        normalized=replace(command,file_name=self._text(command.file_name,"file_name",260),content_type=self._text(command.content_type,"content_type",160),content_sha256=self._sha(command.content_sha256),storage_provider=self._code(command.storage_provider,"storage_provider"),storage_key=self._text(command.storage_key,"storage_key",500),created_by_reference=self._text(command.created_by_reference,"created_by_reference",180) if command.created_by_reference else None)
        value=self.repository.register_version(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if value is None:raise SO7AuthorityError("SO7_STALE_DOCUMENT","stale_version","The document changed before the file version was registered",retryable=True)
        return value
    def version(self,tenant_id,public_id):
        self._permit(tenant_id,"document.read","document_version",public_id);value=self.repository.version(tenant_id,public_id)
        if value is None:raise SO7AuthorityError("SO7_VERSION_NOT_FOUND","not_found","The document version was not found")
        return value
    def versions(self,tenant_id,document_public_id):
        self._permit(tenant_id,"document.read","document",document_public_id)
        if self.repository.document(tenant_id,document_public_id) is None:raise SO7AuthorityError("SO7_DOCUMENT_NOT_FOUND","not_found","The document was not found")
        return self.repository.versions(tenant_id,document_public_id)
    def current_version(self,tenant_id,document_public_id):
        self._permit(tenant_id,"document.read","document",document_public_id);value=self.repository.current_version(tenant_id,document_public_id)
        if value is None:raise SO7AuthorityError("SO7_VERSION_NOT_FOUND","not_found","The document has no registered file version")
        return value
    def link_evidence(self,command:LinkEvidence):
        self._permit(command.tenant_id,"document.evidence.link","document",command.document_public_id)
        current=self.repository.document(command.tenant_id,command.document_public_id)
        if current is None:raise SO7AuthorityError("SO7_DOCUMENT_NOT_FOUND","not_found","The document was not found")
        if current.status is DocumentStatus.WITHDRAWN:raise SO7AuthorityError("SO7_DOCUMENT_WITHDRAWN","invalid_state_transition","Withdrawn documents cannot be newly linked as evidence")
        authority,reference=self._subject(command.tenant_id,command.subject_authority,command.subject_reference)
        normalized=replace(command,subject_authority=authority,subject_reference=reference,relation_code=self._code(command.relation_code,"relation_code"))
        if command.version_public_id:
            version=self.repository.version(command.tenant_id,command.version_public_id)
            if version is None or version.document_public_id!=command.document_public_id:raise SO7AuthorityError("SO7_VERSION_SCOPE_MISMATCH","scope_mismatch","The evidence version does not belong to this document and tenant")
        value=self.repository.link_evidence(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if value is None:raise SO7AuthorityError("SO7_EVIDENCE_CONFLICT","stale_version","The evidence link could not be created from the requested document state",retryable=True)
        return value
    def evidence(self,tenant_id,public_id):
        self._permit(tenant_id,"document.evidence.read","evidence",public_id);value=self.repository.evidence(tenant_id,public_id)
        if value is None:raise SO7AuthorityError("SO7_EVIDENCE_NOT_FOUND","not_found","The evidence link was not found")
        return value
    def evidence_for_subject(self,tenant_id,subject_authority,subject_reference,include_history=False):
        self._permit(tenant_id,"document.evidence.read")
        authority,reference=self._subject(tenant_id,subject_authority,subject_reference)
        return self.repository.evidence_for_subject(tenant_id,authority,reference,include_history)
    def end_evidence(self,command:EndEvidenceLink):
        self._permit(command.tenant_id,"document.evidence.end","evidence",command.link_public_id)
        current=self.repository.evidence(command.tenant_id,command.link_public_id)
        if current is None:raise SO7AuthorityError("SO7_EVIDENCE_NOT_FOUND","not_found","The evidence link was not found")
        if current.status is EvidenceStatus.ENDED:raise SO7AuthorityError("SO7_EVIDENCE_ENDED","invalid_state_transition","The evidence link has already ended")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        value=self.repository.end_evidence(normalized,self._fingerprint(normalized))
        if value is None:raise SO7AuthorityError("SO7_STALE_EVIDENCE","stale_version","The evidence link changed before it was ended",retryable=True)
        return value
    def change_status(self,command:ChangeDocumentStatus):
        self._permit(command.tenant_id,"document.status.change","document",command.document_public_id)
        current=self.repository.document(command.tenant_id,command.document_public_id)
        if current is None:raise SO7AuthorityError("SO7_DOCUMENT_NOT_FOUND","not_found","The document was not found")
        allowed={DocumentStatus.ACTIVE:{DocumentStatus.ARCHIVED,DocumentStatus.WITHDRAWN},DocumentStatus.ARCHIVED:{DocumentStatus.ACTIVE,DocumentStatus.WITHDRAWN},DocumentStatus.WITHDRAWN:set()}
        if command.to_status not in allowed[current.status]:raise SO7AuthorityError("SO7_INVALID_DOCUMENT_TRANSITION","invalid_state_transition","The document lifecycle transition is not permitted")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        value=self.repository.change_status(normalized,self._fingerprint(normalized))
        if value is None:raise SO7AuthorityError("SO7_STALE_DOCUMENT","stale_version","The document changed before its status was updated",retryable=True)
        return value
    def search(self,tenant_id,query=None,classification_code=None,status=None,limit=50):
        self._permit(tenant_id,"document.search")
        if not isinstance(limit,int) or limit<1 or limit>100:raise SO7AuthorityError("SO7_INVALID_SEARCH_LIMIT","validation_failure","Search limit must be between 1 and 100")
        q=self._text(query,"query",240) if query else None
        code=self._classification(tenant_id,classification_code) if classification_code else None
        return self.repository.search(tenant_id,q,code,status,limit)
