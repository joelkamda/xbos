"""SO5 neutral resource and operational assignment authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class SO5AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code; self.category=category; self.safe_explanation=explanation; self.retryable=retryable
        super().__init__(code)

class SO5Repository(Protocol):
    def create_resource(self,command,public_id,fingerprint)->Resource: ...
    def resource(self,tenant_id,public_id)->Resource|None: ...
    def list_resources(self,tenant_id,classification_code=None): ...
    def change_status(self,command,fingerprint)->Resource|None: ...
    def assign(self,command,public_id,fingerprint)->OperationalAssignment|None: ...
    def assignment(self,tenant_id,public_id)->OperationalAssignment|None: ...
    def end_assignment(self,command,fingerprint)->OperationalAssignment|None: ...
    def assignments(self,tenant_id,resource_public_id,include_history=False): ...
    def history(self,tenant_id,resource_public_id): ...

class SO5Authority:
    def __init__(self,repository:SO5Repository,*,party_resolver:Callable,identity_resolver:Callable,
                 organization_resolver:Callable,location_resolver:Callable,authorize:Callable,
                 public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository; self.party_resolver=party_resolver; self.identity_resolver=identity_resolver
        self.organization_resolver=organization_resolver; self.location_resolver=location_resolver
        self.authorize=authorize; self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command): return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
            raise SO5AuthorityError("SO5_INVALID_"+field.upper(),"validation_failure",field+" must be a neutral code")
        return value
    def _permit(self,tenant,permission):
        if not self.authorize(tenant,permission,"tenant",tenant):
            raise SO5AuthorityError("SO5_PERMISSION_DENIED","permission_denied","The resource operation is not permitted")
    @staticmethod
    def _owned(value,tenant,public_id,code):
        if value is None or getattr(value,"tenant_id",None)!=tenant or UUID(str(getattr(value,"public_id",UUID(int=0))))!=public_id:
            raise SO5AuthorityError(code,"scope_mismatch","The referenced authority was not found in this tenant")
        return value
    def _resolve_context(self,tenant,organization_public_id,location_public_id):
        if organization_public_id:self._owned(self.organization_resolver(tenant,organization_public_id),tenant,organization_public_id,"SO5_ORGANIZATION_NOT_FOUND")
        if location_public_id:self._owned(self.location_resolver(tenant,location_public_id),tenant,location_public_id,"SO5_LOCATION_NOT_FOUND")
    def create_resource(self,command:CreateResource):
        self._permit(command.tenant_id,"resource.create")
        if isinstance(command.capacity,bool) or command.capacity<1: raise SO5AuthorityError("SO5_INVALID_CAPACITY","validation_failure","Resource capacity must be a positive integer")
        label=command.display_label.strip()
        if not label: raise SO5AuthorityError("SO5_DISPLAY_LABEL_REQUIRED","validation_failure","Resource display label is required")
        classification=self._code(command.classification_code,"classification_code")
        if command.resource_kind is ResourceKind.PERSON:
            if not command.party_public_id: raise SO5AuthorityError("SO5_PERSON_PARTY_REQUIRED","validation_failure","Person-backed resources require PC2 Party")
            self._owned(self.party_resolver(command.tenant_id,command.party_public_id),command.tenant_id,command.party_public_id,"SO5_PARTY_NOT_FOUND")
        elif command.party_public_id:
            raise SO5AuthorityError("SO5_NON_PERSON_PARTY_FORBIDDEN","validation_failure","Non-person resources do not use fake Party identity")
        if command.identity_public_id:
            if command.resource_kind is not ResourceKind.PERSON: raise SO5AuthorityError("SO5_NON_PERSON_IDENTITY_FORBIDDEN","validation_failure","Non-person resources cannot bind a human identity")
            identity=self._owned(self.identity_resolver(command.tenant_id,command.identity_public_id),command.tenant_id,command.identity_public_id,"SO5_IDENTITY_NOT_FOUND")
            linked=getattr(identity,"party_public_id",None)
            if linked is not None and UUID(str(linked))!=command.party_public_id: raise SO5AuthorityError("SO5_IDENTITY_PARTY_MISMATCH","scope_mismatch","Identity and resource Party association disagree")
        self._resolve_context(command.tenant_id,command.organization_unit_public_id,command.location_public_id)
        normalized=replace(command,classification_code=classification,display_label=label)
        return self.repository.create_resource(normalized,self.public_id_factory(),self._fingerprint(normalized))
    def resource(self,tenant_id,public_id):
        self._permit(tenant_id,"resource.read"); value=self.repository.resource(tenant_id,public_id)
        if value is None: raise SO5AuthorityError("SO5_RESOURCE_NOT_FOUND","not_found","The resource was not found")
        return value
    def list_resources(self,tenant_id,classification_code=None):
        self._permit(tenant_id,"resource.read")
        return self.repository.list_resources(tenant_id,self._code(classification_code,"classification_code") if classification_code else None)
    def change_status(self,command:ChangeResourceStatus):
        self._permit(command.tenant_id,"resource.status.change")
        current=self.repository.resource(command.tenant_id,command.resource_public_id)
        if current is None:raise SO5AuthorityError("SO5_RESOURCE_NOT_FOUND","not_found","The resource was not found")
        if current.status is ResourceStatus.RETIRED:raise SO5AuthorityError("SO5_RESOURCE_RETIRED","invalid_state_transition","Retired resources cannot change state")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.change_status(normalized,self._fingerprint(normalized))
        if result is None:raise SO5AuthorityError("SO5_STALE_VERSION","stale_version","The resource changed; reload before retrying",retryable=True)
        return result
    def assign(self,command:AssignResource):
        self._permit(command.tenant_id,"resource.assignment.create")
        if command.effective_to is not None and command.effective_to<=command.effective_from:raise SO5AuthorityError("SO5_INVALID_ASSIGNMENT_PERIOD","validation_failure","Assignment end must be after its start")
        current=self.repository.resource(command.tenant_id,command.resource_public_id)
        if current is None:raise SO5AuthorityError("SO5_RESOURCE_NOT_FOUND","not_found","The resource was not found")
        if current.status is not ResourceStatus.ACTIVE:raise SO5AuthorityError("SO5_RESOURCE_NOT_ACTIVE","invalid_state_transition","Only active resources may be assigned")
        self._resolve_context(command.tenant_id,command.organization_unit_public_id,command.location_public_id)
        normalized=replace(command,capability_code=self._code(command.capability_code,"capability_code"))
        result=self.repository.assign(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO5AuthorityError("SO5_ASSIGNMENT_CONFLICT","conflict","Resource version or assignment exclusivity conflict",retryable=True)
        return result
    def assignment(self,tenant_id,public_id):
        self._permit(tenant_id,"resource.assignment.read"); value=self.repository.assignment(tenant_id,public_id)
        if value is None: raise SO5AuthorityError("SO5_ASSIGNMENT_NOT_FOUND","not_found","The assignment was not found")
        return value
    def end_assignment(self,command:EndAssignment):
        self._permit(command.tenant_id,"resource.assignment.end")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.end_assignment(normalized,self._fingerprint(normalized))
        if result is None:raise SO5AuthorityError("SO5_STALE_ASSIGNMENT","stale_version","The assignment changed; reload before retrying",retryable=True)
        return result
    def assignments(self,tenant_id,resource_public_id,include_history=False):
        self._permit(tenant_id,"resource.assignment.read")
        if self.repository.resource(tenant_id,resource_public_id) is None:raise SO5AuthorityError("SO5_RESOURCE_NOT_FOUND","not_found","The resource was not found")
        return self.repository.assignments(tenant_id,resource_public_id,include_history)
    def history(self,tenant_id,resource_public_id):
        self._permit(tenant_id,"resource.history.read")
        if self.repository.resource(tenant_id,resource_public_id) is None:raise SO5AuthorityError("SO5_RESOURCE_NOT_FOUND","not_found","The resource was not found")
        return self.repository.history(tenant_id,resource_public_id)
