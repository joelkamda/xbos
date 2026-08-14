"""SO8 provider-neutral delivery, inbound integration, and offline synchronization authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class SO8AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable
        super().__init__(code)

class SO8Repository(Protocol):
    def create_delivery(self,command,public_id,fingerprint,payload_sha256)->DeliveryJob: ...
    def delivery(self,tenant_id,public_id)->DeliveryJob|None: ...
    def list_deliveries(self,tenant_id,status=None): ...
    def due_deliveries(self,tenant_id,as_of,limit=50): ...
    def claim_delivery(self,command,fingerprint)->DeliveryJob|None: ...
    def record_attempt(self,command,public_id,fingerprint)->DeliveryJob|None: ...
    def attempts(self,tenant_id,job_public_id): ...
    def cancel_delivery(self,command,fingerprint)->DeliveryJob|None: ...
    def receive_inbound(self,command,public_id,fingerprint)->InboundDelivery: ...
    def inbound(self,tenant_id,public_id)->InboundDelivery|None: ...
    def list_inbound(self,tenant_id,source_code=None): ...
    def queue_offline(self,command,public_id,history_public_id,fingerprint,payload_sha256)->OfflineCommand: ...
    def offline(self,tenant_id,public_id)->OfflineCommand|None: ...
    def list_offline(self,tenant_id,status=None): ...
    def resolve_offline(self,command,history_public_id,fingerprint)->OfflineCommand|None: ...
    def offline_history(self,tenant_id,offline_public_id): ...

class SO8Authority:
    def __init__(self,repository:SO8Repository,*,authorize:Callable,subject_resolver:Callable|None=None,
                 document_version_resolver:Callable|None=None,device_resolver:Callable|None=None,
                 public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository;self.authorize=authorize;self.subject_resolver=subject_resolver
        self.document_version_resolver=document_version_resolver;self.device_resolver=device_resolver;self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command):return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _payload_hash(payload):return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or len(value)>160 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
            raise SO8AuthorityError("SO8_INVALID_"+field.upper(),"validation_failure",field+" must be a bounded neutral code")
        return value
    @staticmethod
    def _text(value,field,max_length=500):
        value=value.strip()
        if not value or len(value)>max_length:raise SO8AuthorityError("SO8_INVALID_"+field.upper(),"validation_failure",field+" is required and bounded")
        return value
    @staticmethod
    def _sha(value):
        value=value.strip().lower()
        if len(value)!=64 or any(c not in "0123456789abcdef" for c in value):raise SO8AuthorityError("SO8_INVALID_PAYLOAD_SHA256","validation_failure","payload_sha256 must be lowercase SHA-256")
        return value
    @staticmethod
    def _object(value):
        if not isinstance(value,dict):raise SO8AuthorityError("SO8_INVALID_PAYLOAD","validation_failure","payload must be an object")
        return value
    def _permit(self,tenant,permission,scope_type="tenant",scope_id=None):
        if not self.authorize(tenant,permission,scope_type,tenant if scope_id is None else scope_id):
            raise SO8AuthorityError("SO8_PERMISSION_DENIED","permission_denied","The delivery operation is not permitted")
    def _subject(self,tenant,authority,reference):
        if authority is None and reference is None:return None,None
        if not authority or not reference:raise SO8AuthorityError("SO8_INVALID_SUBJECT","validation_failure","subject authority and reference must be supplied together")
        authority=self._code(authority,"subject_authority");reference=self._text(reference,"subject_reference",240)
        if self.subject_resolver and not self.subject_resolver(tenant,authority,reference):raise SO8AuthorityError("SO8_SUBJECT_NOT_FOUND","scope_mismatch","The delivery subject was not found in this tenant")
        return authority,reference
    def create_delivery(self,command:CreateDeliveryJob):
        self._permit(command.tenant_id,"delivery.create")
        if command.max_attempts<1 or command.max_attempts>100:raise SO8AuthorityError("SO8_INVALID_MAX_ATTEMPTS","validation_failure","max_attempts must be between 1 and 100")
        payload=self._object(command.payload);a,r=self._subject(command.tenant_id,command.subject_authority,command.subject_reference)
        if command.document_version_public_id is not None and self.document_version_resolver and not self.document_version_resolver(command.tenant_id,command.document_version_public_id):
            raise SO8AuthorityError("SO8_DOCUMENT_VERSION_NOT_FOUND","scope_mismatch","The SO7 document version was not found in this tenant")
        normalized=replace(command,delivery_kind=self._code(command.delivery_kind,"delivery_kind"),channel_code=self._code(command.channel_code,"channel_code"),destination_reference=self._text(command.destination_reference,"destination_reference"),payload=payload,subject_authority=a,subject_reference=r)
        return self.repository.create_delivery(normalized,self.public_id_factory(),self._fingerprint(normalized),self._payload_hash(payload))
    def delivery(self,tenant_id,public_id):
        self._permit(tenant_id,"delivery.read","delivery",public_id);value=self.repository.delivery(tenant_id,public_id)
        if value is None:raise SO8AuthorityError("SO8_DELIVERY_NOT_FOUND","not_found","The delivery job was not found")
        return value
    def list_deliveries(self,tenant_id,status=None):self._permit(tenant_id,"delivery.read");return self.repository.list_deliveries(tenant_id,status)
    def due_deliveries(self,tenant_id,as_of,limit=50):
        self._permit(tenant_id,"delivery.dispatch")
        if limit<1 or limit>200:raise SO8AuthorityError("SO8_INVALID_LIMIT","validation_failure","limit must be between 1 and 200")
        return self.repository.due_deliveries(tenant_id,as_of,limit)
    def claim_delivery(self,command:ClaimDeliveryJob):
        self._permit(command.tenant_id,"delivery.dispatch","delivery",command.job_public_id)
        if command.lease_until<=command.occurred_at:raise SO8AuthorityError("SO8_INVALID_LEASE","validation_failure","lease_until must be after occurred_at")
        normalized=replace(command,worker_reference=self._text(command.worker_reference,"worker_reference",180))
        value=self.repository.claim_delivery(normalized,self._fingerprint(normalized))
        if value is None:raise SO8AuthorityError("SO8_DELIVERY_CLAIM_CONFLICT","stale_version","The delivery job is not claimable from the requested state",retryable=True)
        return value
    def record_attempt(self,command:RecordDeliveryAttempt):
        self._permit(command.tenant_id,"delivery.dispatch","delivery",command.job_public_id)
        if not isinstance(command.outcome,AttemptOutcome):raise SO8AuthorityError("SO8_INVALID_ATTEMPT_OUTCOME","validation_failure","attempt outcome is invalid")
        provider=self._code(command.provider_code,"provider_code");metadata=self._object(command.response_metadata)
        if command.outcome is AttemptOutcome.RETRYABLE_FAILURE:
            if command.retry_at is None or command.retry_at<=command.occurred_at:raise SO8AuthorityError("SO8_INVALID_RETRY_AT","validation_failure","retryable failure requires retry_at after occurred_at")
        elif command.retry_at is not None:raise SO8AuthorityError("SO8_UNEXPECTED_RETRY_AT","validation_failure","retry_at is only valid for retryable failures")
        if command.outcome is AttemptOutcome.DELIVERED and command.error_code is not None:raise SO8AuthorityError("SO8_DELIVERED_WITH_ERROR","validation_failure","delivered attempt cannot carry an error code")
        normalized=replace(command,provider_code=provider,provider_reference=self._text(command.provider_reference,"provider_reference",240) if command.provider_reference else None,error_code=self._code(command.error_code,"error_code") if command.error_code else None,response_metadata=metadata)
        value=self.repository.record_attempt(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if value is None:raise SO8AuthorityError("SO8_DELIVERY_ATTEMPT_CONFLICT","stale_version","The delivery job changed before the attempt was recorded",retryable=True)
        return value
    def attempts(self,tenant_id,job_public_id):self._permit(tenant_id,"delivery.read","delivery",job_public_id);return self.repository.attempts(tenant_id,job_public_id)
    def cancel_delivery(self,command:CancelDeliveryJob):
        self._permit(command.tenant_id,"delivery.cancel","delivery",command.job_public_id)
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"));value=self.repository.cancel_delivery(normalized,self._fingerprint(normalized))
        if value is None:raise SO8AuthorityError("SO8_DELIVERY_CANCEL_CONFLICT","invalid_state_transition","The delivery job cannot be cancelled from its current state")
        return value
    def receive_inbound(self,command:ReceiveInboundDelivery):
        self._permit(command.tenant_id,"integration.receive")
        payload=self._object(command.payload);a,r=self._subject(command.tenant_id,command.subject_authority,command.subject_reference)
        normalized=replace(command,source_code=self._code(command.source_code,"source_code"),external_event_key=self._text(command.external_event_key,"external_event_key",240),payload_sha256=self._sha(command.payload_sha256),payload=payload,subject_authority=a,subject_reference=r)
        return self.repository.receive_inbound(normalized,self.public_id_factory(),self._fingerprint(normalized))
    def inbound(self,tenant_id,public_id):
        self._permit(tenant_id,"integration.read","inbound_delivery",public_id);value=self.repository.inbound(tenant_id,public_id)
        if value is None:raise SO8AuthorityError("SO8_INBOUND_NOT_FOUND","not_found","The inbound delivery was not found")
        return value
    def list_inbound(self,tenant_id,source_code=None):self._permit(tenant_id,"integration.read");return self.repository.list_inbound(tenant_id,self._code(source_code,"source_code") if source_code else None)
    def queue_offline(self,command:QueueOfflineCommand):
        self._permit(command.tenant_id,"offline.queue")
        if command.client_sequence<0:raise SO8AuthorityError("SO8_INVALID_CLIENT_SEQUENCE","validation_failure","client_sequence must be non-negative")
        if command.base_version is not None and command.base_version<0:raise SO8AuthorityError("SO8_INVALID_BASE_VERSION","validation_failure","base_version must be non-negative")
        if self.device_resolver and not self.device_resolver(command.tenant_id,command.device_public_id):raise SO8AuthorityError("SO8_DEVICE_NOT_FOUND","scope_mismatch","The PC5 device identity was not found in this tenant")
        payload=self._object(command.payload);normalized=replace(command,operation_code=self._code(command.operation_code,"operation_code"),target_authority=self._code(command.target_authority,"target_authority"),target_reference=self._text(command.target_reference,"target_reference",240),payload=payload)
        return self.repository.queue_offline(normalized,self.public_id_factory(),self.public_id_factory(),self._fingerprint(normalized),self._payload_hash(payload))
    def offline(self,tenant_id,public_id):
        self._permit(tenant_id,"offline.read","offline_command",public_id);value=self.repository.offline(tenant_id,public_id)
        if value is None:raise SO8AuthorityError("SO8_OFFLINE_NOT_FOUND","not_found","The offline command was not found")
        return value
    def list_offline(self,tenant_id,status=None):self._permit(tenant_id,"offline.read");return self.repository.list_offline(tenant_id,status)
    def resolve_offline(self,command:ResolveOfflineCommand):
        self._permit(command.tenant_id,"offline.resolve","offline_command",command.offline_command_public_id)
        if command.to_status not in {OfflineStatus.APPLIED,OfflineStatus.CONFLICT,OfflineStatus.REJECTED}:raise SO8AuthorityError("SO8_INVALID_OFFLINE_RESOLUTION","validation_failure","offline resolution must be applied, conflict, or rejected")
        if command.to_status is OfflineStatus.APPLIED and not command.server_result_reference:raise SO8AuthorityError("SO8_RESULT_REFERENCE_REQUIRED","validation_failure","applied offline command requires server result reference")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"),server_result_reference=self._text(command.server_result_reference,"server_result_reference",240) if command.server_result_reference else None)
        value=self.repository.resolve_offline(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if value is None:raise SO8AuthorityError("SO8_OFFLINE_RESOLUTION_CONFLICT","stale_version","The offline command is no longer queued at the requested version",retryable=True)
        return value
    def offline_history(self,tenant_id,offline_public_id):self._permit(tenant_id,"offline.read","offline_command",offline_public_id);return self.repository.offline_history(tenant_id,offline_public_id)
