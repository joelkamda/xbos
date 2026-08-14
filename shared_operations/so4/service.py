"""Neutral SO4 authority. Supplier, item, stock and approval truth remain external."""

from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from typing import Callable,Protocol
from uuid import UUID,uuid4
from shared_operations.so3 import MoveStock
from .contracts import *


class SO4AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable
        super().__init__(code)


class SO4Repository(Protocol):
    def create_request(self,command,lines,public_id,fingerprint)->PurchaseRequest: ...
    def create_order(self,command,party_id,relationship_id,request_id,lines,public_id,fingerprint)->PurchaseOrder: ...
    def request(self,tenant_id,public_id)->PurchaseRequest|None: ...
    def order(self,tenant_id,public_id)->PurchaseOrder|None: ...
    def transition(self,command,fingerprint,is_order:bool): ...
    def begin_receipt(self,command,public_id,fingerprint): ...
    def complete_receipt(self,command,receipt_public_id,movements): ...
    def receipt(self,tenant_id,public_id)->ProcurementReceipt|None: ...
    def history(self,tenant_id,resource_public_id): ...


_TRANSITIONS={
 ProcurementStatus.DRAFT:{ProcurementStatus.SUBMITTED,ProcurementStatus.CANCELLED},
 ProcurementStatus.SUBMITTED:{ProcurementStatus.APPROVED,ProcurementStatus.CANCELLED},
 ProcurementStatus.APPROVED:{ProcurementStatus.ORDERED,ProcurementStatus.CANCELLED},
 ProcurementStatus.ORDERED:{ProcurementStatus.PARTIALLY_RECEIVED,ProcurementStatus.RECEIVED,ProcurementStatus.CANCELLED},
 ProcurementStatus.PARTIALLY_RECEIVED:{ProcurementStatus.PARTIALLY_RECEIVED,ProcurementStatus.RECEIVED,ProcurementStatus.CLOSED},
 ProcurementStatus.RECEIVED:{ProcurementStatus.CLOSED}, ProcurementStatus.CANCELLED:set(), ProcurementStatus.CLOSED:set(),
}


class SO4Authority:
    def __init__(self,repository:SO4Repository,*,party_resolver:Callable,relationship_resolver:Callable,
                 atomic_unit_resolver:Callable,stock_location_resolver:Callable,inventory_authority,
                 authorize:Callable,approval_validator:Callable=lambda *_:True,
                 over_receipt_authorizer:Callable=lambda *_:False,public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository;self.party_resolver=party_resolver;self.relationship_resolver=relationship_resolver
        self.atomic_unit_resolver=atomic_unit_resolver;self.stock_location_resolver=stock_location_resolver
        self.inventory_authority=inventory_authority;self.authorize=authorize;self.approval_validator=approval_validator
        self.over_receipt_authorizer=over_receipt_authorizer;self.public_id_factory=public_id_factory

    @staticmethod
    def _fingerprint(command): return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value): raise SO4AuthorityError("SO4_INVALID_"+field.upper(),"validation_failure",field+" must be a neutral code")
        return value
    def _permit(self,tenant,permission):
        if not self.authorize(tenant,permission,"tenant",tenant): raise SO4AuthorityError("SO4_PERMISSION_DENIED","permission_denied","The procurement operation is not permitted")
    @staticmethod
    def _owned(value,tenant,public_id,code):
        if value is None or getattr(value,"tenant_id",None)!=tenant or UUID(str(getattr(value,"public_id",UUID(int=0))))!=public_id: raise SO4AuthorityError(code,"scope_mismatch","The referenced authority was not found in this tenant")
        return value
    def _lines(self,tenant,lines):
        if not lines: raise SO4AuthorityError("SO4_LINES_REQUIRED","validation_failure","At least one procurement line is required")
        seen=set(); result=[]
        for line in lines:
            if isinstance(line.quantity,bool) or line.quantity<=0 or line.line_number in seen: raise SO4AuthorityError("SO4_INVALID_LINE","validation_failure","Line numbers must be unique and quantities positive")
            seen.add(line.line_number); desc=line.description.strip()
            if line.line_type is LineType.STOCK:
                if not line.atomic_unit_public_id or not line.stock_location_public_id: raise SO4AuthorityError("SO4_STOCK_AUTHORITIES_REQUIRED","validation_failure","Stock lines require SO1 Atomic Unit and SO3 stock location")
                self._owned(self.atomic_unit_resolver(tenant,line.atomic_unit_public_id),tenant,line.atomic_unit_public_id,"SO4_ATOMIC_UNIT_NOT_FOUND")
                self._owned(self.stock_location_resolver(tenant,line.stock_location_public_id),tenant,line.stock_location_public_id,"SO4_STOCK_LOCATION_NOT_FOUND")
            elif not desc: raise SO4AuthorityError("SO4_SERVICE_DESCRIPTION_REQUIRED","validation_failure","Service lines require a description")
            elif line.atomic_unit_public_id: self._owned(self.atomic_unit_resolver(tenant,line.atomic_unit_public_id),tenant,line.atomic_unit_public_id,"SO4_ATOMIC_UNIT_NOT_FOUND")
            result.append(replace(line,description=desc))
        return tuple(result)
    def create_request(self,command:CreatePurchaseRequest):
        self._permit(command.tenant_id,"procurement.request.create"); lines=self._lines(command.tenant_id,command.lines)
        normalized=replace(command,request_code=self._code(command.request_code,"request_code"),lines=lines)
        return self.repository.create_request(normalized,lines,self.public_id_factory(),self._fingerprint(normalized))
    def request(self,tenant_id:int,public_id:UUID):
        self._permit(tenant_id,"procurement.request.read");value=self.repository.request(tenant_id,public_id)
        if value is None:raise SO4AuthorityError("SO4_REQUEST_NOT_FOUND","not_found","The purchase request was not found")
        return value
    def order(self,tenant_id:int,public_id:UUID):
        self._permit(tenant_id,"procurement.order.read");value=self.repository.order(tenant_id,public_id)
        if value is None:raise SO4AuthorityError("SO4_ORDER_NOT_FOUND","not_found","The purchase order was not found")
        return value
    def history(self,tenant_id:int,public_id:UUID):
        self._permit(tenant_id,"procurement.history.read");return self.repository.history(tenant_id,public_id)
    def create_order(self,command:CreatePurchaseOrder):
        self._permit(command.tenant_id,"procurement.order.create")
        party=self._owned(self.party_resolver(command.tenant_id,command.supplier_party_public_id),command.tenant_id,command.supplier_party_public_id,"SO4_SUPPLIER_PARTY_NOT_FOUND")
        relationship=self._owned(self.relationship_resolver(command.tenant_id,command.supplier_relationship_public_id),command.tenant_id,command.supplier_relationship_public_id,"SO4_SUPPLIER_RELATIONSHIP_NOT_FOUND")
        if UUID(str(relationship.party_public_id))!=command.supplier_party_public_id or relationship.relationship_type_code not in {"supplier","vendor"} or str(relationship.status)!="active": raise SO4AuthorityError("SO4_INVALID_SUPPLIER_RELATIONSHIP","validation_failure","An active SO2 supplier relationship for this Party is required")
        request_id=None
        if command.request_public_id:
            request=self.repository.request(command.tenant_id,command.request_public_id)
            if request is None: raise SO4AuthorityError("SO4_REQUEST_NOT_FOUND","scope_mismatch","The purchase request was not found in this tenant")
            request_id=request.public_id
        lines=self._lines(command.tenant_id,command.lines); normalized=replace(command,order_code=self._code(command.order_code,"order_code"),lines=lines)
        return self.repository.create_order(normalized,int(party.id),int(relationship.id),request_id,lines,self.public_id_factory(),self._fingerprint(normalized))
    def _transition(self,command,is_order):
        self._permit(command.tenant_id,"procurement.order.lifecycle" if is_order else "procurement.request.lifecycle")
        current=self.repository.order(command.tenant_id,command.resource_public_id) if is_order else self.repository.request(command.tenant_id,command.resource_public_id)
        if current is None: raise SO4AuthorityError("SO4_RESOURCE_NOT_FOUND","not_found","The procurement resource was not found")
        if command.to_status not in _TRANSITIONS[current.status]: raise SO4AuthorityError("SO4_INVALID_STATE_TRANSITION","invalid_state_transition","The requested transition is not allowed")
        if command.to_status is ProcurementStatus.APPROVED and not self.approval_validator(command.tenant_id,command.approval_public_id,"procurement.approve",command.resource_public_id): raise SO4AuthorityError("SO4_APPROVAL_REQUIRED","approval_required","An accepted PC5 approval decision is required")
        result=self.repository.transition(command,self._fingerprint(command),is_order)
        if result is None: raise SO4AuthorityError("SO4_STALE_VERSION","stale_version","The procurement resource changed; reload before retrying",retryable=True)
        return result
    def transition_request(self,command): return self._transition(command,False)
    def transition_order(self,command): return self._transition(command,True)
    def receive(self,command:ReceivePurchaseOrder):
        self._permit(command.tenant_id,"procurement.receipt.accept")
        if not command.lines or any(isinstance(x.quantity,bool) or x.quantity<=0 for x in command.lines): raise SO4AuthorityError("SO4_INVALID_RECEIPT","validation_failure","Receipt quantities must be positive")
        receipt_id=self.public_id_factory(); replay,plan=self.repository.begin_receipt(command,receipt_id,self._fingerprint(command))
        if replay: return replay
        movements=[]
        for index,line in enumerate(plan,1):
            if line["quantity"]>line["outstanding"] and line["policy"]==OverReceiptPolicy.FORBID.value: raise SO4AuthorityError("SO4_OVER_RECEIPT_FORBIDDEN","conflict","Receipt exceeds outstanding quantity")
            if line["quantity"]>line["outstanding"] and not self.over_receipt_authorizer(command.tenant_id,command.purchase_order_public_id,line["order_line_public_id"],line["quantity"]): raise SO4AuthorityError("SO4_OVER_RECEIPT_AUTHORIZATION_REQUIRED","permission_denied","Over-receipt requires explicit policy authorization")
            if line["line_type"]==LineType.STOCK.value:
                _,movement=self.inventory_authority.receive(MoveStock(command_key=f"so4:{receipt_id}:{index}",tenant_id=command.tenant_id,atomic_unit_public_id=line["atomic_unit_public_id"],stock_location_public_id=line["location_public_id"],quantity=line["quantity"],reason_code="procurement-receipt",occurred_at=command.occurred_at,source_type="so4-procurement",source_reference=str(receipt_id),metadata={"purchase_order":str(command.purchase_order_public_id),"receipt":str(receipt_id)}))
                movements.append((line["order_line_public_id"],movement.public_id))
        return self.repository.complete_receipt(command,receipt_id,movements)
