from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from datetime import datetime,timezone
from decimal import Decimal
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class R1Error(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable;super().__init__(code)

class R1Repository(Protocol):
    def define_mode(self,c,p,fp)->ServiceMode|None: ...
    def mode(self,t,code)->ServiceMode|None: ...
    def modes(self,t)->tuple[ServiceMode,...]: ...
    def profile_resource(self,c,fp)->ResourceProfile|None: ...
    def resource_profile(self,t,p)->ResourceProfile|None: ...
    def open_session(self,c,p,fp)->ServiceSession|None: ...
    def session(self,t,p)->ServiceSession|None: ...
    def close_session(self,c,fp)->ServiceSession|None: ...
    def open_order(self,c,p,fp)->RestaurantOrder|None: ...
    def order(self,t,p)->RestaurantOrder|None: ...
    def add_line(self,c,p,price,currency,fp)->RestaurantOrder|None: ...
    def submit_order(self,c,fp)->RestaurantOrder|None: ...
    def cancel_order(self,c,fp)->RestaurantOrder|None: ...
    def open_tab(self,c,p,fp)->RestaurantTab|None: ...
    def tab(self,t,p)->RestaurantTab|None: ...
    def attach_order(self,c,fp)->RestaurantTab|None: ...
    def tab_line_quantities(self,t,p)->dict[UUID,Decimal]: ...
    def partition_tab(self,c,public_ids,fp)->tuple[RestaurantTab,tuple[TabPartition,...]]|None: ...
    def close_tab(self,c,fp)->RestaurantTab|None: ...

class R1Authority:
    def __init__(self,repo:R1Repository,*,resource_resolver:Callable,party_resolver:Callable,identity_resolver:Callable,offer_resolver:Callable,atomic_unit_resolver:Callable,price_resolver:Callable,reservation_resolver:Callable,authorize:Callable,public_id_factory:Callable[[],UUID]=uuid4):
        self.repo=repo;self.resource_resolver=resource_resolver;self.party_resolver=party_resolver;self.identity_resolver=identity_resolver;self.offer_resolver=offer_resolver;self.atomic_unit_resolver=atomic_unit_resolver;self.price_resolver=price_resolver;self.reservation_resolver=reservation_resolver;self.authorize=authorize;self.public_id_factory=public_id_factory
    @staticmethod
    def _fp(c):return hashlib.sha256(json.dumps(asdict(c),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    @staticmethod
    def _code(v,f):
        v=v.strip().lower()
        if not v or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789._-' for ch in v):raise R1Error('R1_INVALID_'+f.upper(),'validation_failure',f+' must be a neutral code')
        return v
    @staticmethod
    def _aware(v,f):
        if v.tzinfo is None or v.utcoffset() is None:raise R1Error('R1_NAIVE_DATETIME','validation_failure',f+' must be timezone-aware')
        return v.astimezone(timezone.utc)
    @staticmethod
    def _qty(v):
        q=Decimal(v)
        if not q.is_finite() or q<=0:raise R1Error('R1_INVALID_QUANTITY','validation_failure','quantity must be positive')
        return q
    def _permit(self,t,p):
        if not self.authorize(t,p,'tenant',t):raise R1Error('R1_PERMISSION_DENIED','permission_denied','Restaurant operation is not permitted')
    @staticmethod
    def _owned(v,t,p,code):
        if v is None or getattr(v,'tenant_id',None)!=t or UUID(str(getattr(v,'public_id',UUID(int=0))))!=p:raise R1Error(code,'scope_mismatch','Referenced authority was not found in this tenant')
        return v
    def _staff(self,t,items):
        out=[];seen=set()
        for x in items:
            role=self._code(x.role_code,'staff_role');key=(role,x.party_public_id)
            if key in seen:raise R1Error('R1_DUPLICATE_STAFF','validation_failure','Duplicate Restaurant staff attribution')
            seen.add(key);self._owned(self.party_resolver(t,x.party_public_id),t,x.party_public_id,'R1_PARTY_NOT_FOUND')
            if x.identity_public_id:
                ident=self.identity_resolver(t,x.identity_public_id)
                if ident is None or UUID(str(getattr(ident,'public_id',UUID(int=0))))!=x.identity_public_id:raise R1Error('R1_IDENTITY_NOT_FOUND','scope_mismatch','Identity was not found in this tenant')
                linked=getattr(ident,'party_public_id',None)
                if linked and UUID(str(linked))!=x.party_public_id:raise R1Error('R1_IDENTITY_PARTY_MISMATCH','scope_mismatch','Identity and Party attribution disagree')
            out.append(replace(x,role_code=role))
        return tuple(out)
    def define_mode(self,c:DefineServiceMode):
        self._permit(c.tenant_id,'restaurant.service_mode.define');code=self._code(c.mode_code,'mode_code');name=c.display_name.strip()
        if not name:raise R1Error('R1_MODE_NAME_REQUIRED','validation_failure','Service mode name is required')
        if c.requires_resource and not c.requires_session:raise R1Error('R1_RESOURCE_REQUIRES_SESSION','validation_failure','Resource-required mode must require a service session')
        n=replace(c,mode_code=code,display_name=name);r=self.repo.define_mode(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R1Error('R1_MODE_CONFLICT','conflict','Service mode conflict')
        return r
    def profile_resource(self,c:ProfileResource):
        self._permit(c.tenant_id,'restaurant.resource.profile');self._owned(self.resource_resolver(c.tenant_id,c.resource_public_id),c.tenant_id,c.resource_public_id,'R1_RESOURCE_NOT_FOUND')
        if c.parent_resource_public_id:
            self._owned(self.resource_resolver(c.tenant_id,c.parent_resource_public_id),c.tenant_id,c.parent_resource_public_id,'R1_PARENT_RESOURCE_NOT_FOUND')
            if c.parent_resource_public_id==c.resource_public_id:raise R1Error('R1_RESOURCE_SELF_PARENT','validation_failure','Resource cannot parent itself')
        modes=tuple(sorted({self._code(x,'mode_code') for x in c.service_mode_codes}))
        for m in modes:
            mode=self.repo.mode(c.tenant_id,m)
            if mode is None or not mode.active:raise R1Error('R1_MODE_NOT_ACTIVE','invalid_state_transition','Profile references inactive service mode')
        n=replace(c,service_mode_codes=modes);r=self.repo.profile_resource(n,self._fp(n))
        if r is None:raise R1Error('R1_RESOURCE_PROFILE_CONFLICT','conflict','Resource profile conflict')
        return r
    def open_session(self,c:OpenSession):
        self._permit(c.tenant_id,'restaurant.session.open');code=self._code(c.mode_code,'mode_code');mode=self.repo.mode(c.tenant_id,code)
        if mode is None or not mode.active or not mode.requires_session:raise R1Error('R1_SESSION_MODE_INVALID','invalid_state_transition','Mode does not allow a Restaurant service session')
        if c.guest_count<1:raise R1Error('R1_INVALID_GUEST_COUNT','validation_failure','Guest count must be positive')
        if mode.requires_resource and not c.resource_public_ids:raise R1Error('R1_RESOURCE_REQUIRED','validation_failure','Service mode requires a resource')
        if c.reservation_public_id:
            if not mode.supports_reservations:raise R1Error('R1_RESERVATION_NOT_SUPPORTED','validation_failure','Mode does not support reservations')
            self._owned(self.reservation_resolver(c.tenant_id,c.reservation_public_id),c.tenant_id,c.reservation_public_id,'R1_RESERVATION_NOT_FOUND')
        if c.party_public_id:self._owned(self.party_resolver(c.tenant_id,c.party_public_id),c.tenant_id,c.party_public_id,'R1_PARTY_NOT_FOUND')
        resources=tuple(dict.fromkeys(c.resource_public_ids))
        if len(resources)!=len(c.resource_public_ids):raise R1Error('R1_DUPLICATE_RESOURCE','validation_failure','Duplicate session resource')
        for p in resources:
            self._owned(self.resource_resolver(c.tenant_id,p),c.tenant_id,p,'R1_RESOURCE_NOT_FOUND')
            prof=self.repo.resource_profile(c.tenant_id,p)
            if prof is None or (prof.service_mode_codes and code not in prof.service_mode_codes):raise R1Error('R1_RESOURCE_MODE_MISMATCH','validation_failure','Resource is not profiled for this mode')
        n=replace(c,mode_code=code,opened_at=self._aware(c.opened_at,'opened_at'),resource_public_ids=resources,staff=self._staff(c.tenant_id,c.staff));r=self.repo.open_session(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R1Error('R1_SESSION_CONFLICT','conflict','Session conflict',retryable=True)
        return r
    def close_session(self,c:CloseSession):
        self._permit(c.tenant_id,'restaurant.session.close');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.close_session(n,self._fp(n))
        if r is None:raise R1Error('R1_SESSION_STATE_CONFLICT','stale_version','Session cannot close',retryable=True)
        return r
    def open_order(self,c:OpenOrder):
        self._permit(c.tenant_id,'restaurant.order.open');code=self._code(c.mode_code,'mode_code');src=self._code(c.source_channel_code,'source_channel_code');mode=self.repo.mode(c.tenant_id,code)
        if mode is None or not mode.active:raise R1Error('R1_MODE_NOT_ACTIVE','invalid_state_transition','Active service mode required')
        if c.session_public_id:
            s=self.repo.session(c.tenant_id,c.session_public_id)
            if s is None or s.status is not SessionStatus.OPEN or s.mode_code!=code:raise R1Error('R1_SESSION_MODE_MISMATCH','invalid_state_transition','Order session/mode mismatch')
        elif mode.requires_session:raise R1Error('R1_SESSION_REQUIRED','validation_failure','Service mode requires a session')
        if src!='in_person' and not mode.allows_remote_origin:raise R1Error('R1_REMOTE_NOT_ALLOWED','validation_failure','Remote-origin order not allowed for mode')
        if c.party_public_id:self._owned(self.party_resolver(c.tenant_id,c.party_public_id),c.tenant_id,c.party_public_id,'R1_PARTY_NOT_FOUND')
        n=replace(c,order_code=c.order_code.strip(),mode_code=code,source_channel_code=src,opened_at=self._aware(c.opened_at,'opened_at'),staff=self._staff(c.tenant_id,c.staff))
        if not n.order_code:raise R1Error('R1_ORDER_CODE_REQUIRED','validation_failure','Order code required')
        r=self.repo.open_order(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R1Error('R1_ORDER_CONFLICT','conflict','Order conflict',retryable=True)
        return r
    def add_line(self,c:AddLine):
        self._permit(c.tenant_id,'restaurant.order.change');resolver=self.atomic_unit_resolver if c.target_type is TargetType.ATOMIC_UNIT else self.offer_resolver
        self._owned(resolver(c.tenant_id,c.target_public_id),c.tenant_id,c.target_public_id,'R1_TARGET_NOT_FOUND');price=self._owned(self.price_resolver(c.tenant_id,c.price_public_id),c.tenant_id,c.price_public_id,'R1_PRICE_NOT_FOUND')
        if getattr(getattr(price,'target_type',None),'value',getattr(price,'target_type',None))!=c.target_type.value or UUID(str(getattr(price,'target_public_id',UUID(int=0))))!=c.target_public_id:raise R1Error('R1_PRICE_TARGET_MISMATCH','scope_mismatch','Price does not match target')
        n=replace(c,quantity=self._qty(c.quantity),occurred_at=self._aware(c.occurred_at,'occurred_at'),note=c.note.strip() if c.note else None);r=self.repo.add_line(n,self.public_id_factory(),Decimal(getattr(price,'amount')),str(getattr(price,'currency')).upper(),self._fp(n))
        if r is None:raise R1Error('R1_ORDER_LINE_CONFLICT','stale_version','Order changed or cannot accept line',retryable=True)
        return r
    def submit_order(self,c:SubmitOrder):
        self._permit(c.tenant_id,'restaurant.order.submit');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'));r=self.repo.submit_order(n,self._fp(n))
        if r is None:raise R1Error('R1_ORDER_STATE_CONFLICT','stale_version','Order cannot submit',retryable=True)
        return r
    def cancel_order(self,c:CancelOrder):
        self._permit(c.tenant_id,'restaurant.order.cancel');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.cancel_order(n,self._fp(n))
        if r is None:raise R1Error('R1_ORDER_STATE_CONFLICT','stale_version','Order cannot cancel',retryable=True)
        return r
    def open_tab(self,c:OpenTab):
        self._permit(c.tenant_id,'restaurant.tab.open')
        if c.session_public_id:
            s=self.repo.session(c.tenant_id,c.session_public_id);mode=self.repo.mode(c.tenant_id,s.mode_code) if s else None
            if s is None or s.status is not SessionStatus.OPEN or mode is None or not mode.supports_tabs:raise R1Error('R1_TABS_NOT_SUPPORTED','invalid_state_transition','Open session/mode with tab support required')
        if c.party_public_id:self._owned(self.party_resolver(c.tenant_id,c.party_public_id),c.tenant_id,c.party_public_id,'R1_PARTY_NOT_FOUND')
        n=replace(c,tab_code=c.tab_code.strip(),opened_at=self._aware(c.opened_at,'opened_at'))
        if not n.tab_code:raise R1Error('R1_TAB_CODE_REQUIRED','validation_failure','Tab code required')
        r=self.repo.open_tab(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R1Error('R1_TAB_CONFLICT','conflict','Tab conflict',retryable=True)
        return r
    def attach_order(self,c:AttachOrder):
        self._permit(c.tenant_id,'restaurant.tab.change');o=self.repo.order(c.tenant_id,c.order_public_id)
        if o is None or o.status is OrderStatus.CANCELLED:raise R1Error('R1_ORDER_NOT_ATTACHABLE','invalid_state_transition','Order cannot attach to tab')
        n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'));r=self.repo.attach_order(n,self._fp(n))
        if r is None:raise R1Error('R1_TAB_ORDER_CONFLICT','stale_version','Tab/order grouping conflict',retryable=True)
        return r
    def partition_tab(self,c:PartitionTab):
        self._permit(c.tenant_id,'restaurant.tab.partition')
        if len(c.partitions)<2:raise R1Error('R1_SPLIT_REQUIRES_MULTIPLE_PARTITIONS','validation_failure','At least two partitions required')
        expected=self.repo.tab_line_quantities(c.tenant_id,c.tab_public_id)
        if not expected:raise R1Error('R1_TAB_HAS_NO_LINES','invalid_state_transition','Tab has no lines')
        sums={k:Decimal('0') for k in expected};codes=set();specs=[]
        for s in c.partitions:
            code=self._code(s.partition_code,'partition_code')
            if code in codes:raise R1Error('R1_DUPLICATE_PARTITION_CODE','validation_failure','Duplicate partition code')
            codes.add(code);alloc=[];seen=set()
            for a in s.allocations:
                if a.line_public_id in seen or a.line_public_id not in expected:raise R1Error('R1_PARTITION_LINE_INVALID','scope_mismatch','Invalid partition line')
                seen.add(a.line_public_id);q=self._qty(a.quantity);sums[a.line_public_id]+=q;alloc.append(replace(a,quantity=q))
            if not alloc:raise R1Error('R1_EMPTY_PARTITION','validation_failure','Empty partition')
            specs.append(replace(s,partition_code=code,allocations=tuple(alloc)))
        if any(sums[k]!=Decimal(v) for k,v in expected.items()):raise R1Error('R1_PARTITION_QUANTITY_MISMATCH','validation_failure','Partitions must allocate every line quantity exactly')
        n=replace(c,partitions=tuple(specs),occurred_at=self._aware(c.occurred_at,'occurred_at'));ids=tuple(self.public_id_factory() for _ in n.partitions);r=self.repo.partition_tab(n,ids,self._fp(n))
        if r is None:raise R1Error('R1_TAB_PARTITION_CONFLICT','stale_version','Tab changed while partitioning',retryable=True)
        return r
    def close_tab(self,c:CloseTab):
        self._permit(c.tenant_id,'restaurant.tab.close');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.close_tab(n,self._fp(n))
        if r is None:raise R1Error('R1_TAB_STATE_CONFLICT','stale_version','Tab cannot close',retryable=True)
        return r
    def obligation_handoff(self,t:int,order_public_id:UUID):
        self._permit(t,'restaurant.billing.handoff.read');o=self.repo.order(t,order_public_id)
        if o is None or o.status is not OrderStatus.SUBMITTED or not o.lines:raise R1Error('R1_ORDER_NOT_READY_FOR_FINANCE','invalid_state_transition','Submitted non-empty order required')
        currencies={x.currency for x in o.lines}
        if len(currencies)!=1:raise R1Error('R1_MIXED_CURRENCY_ORDER','validation_failure','One order handoff must use one currency')
        lines=tuple(ObligationHandoffLine(x.public_id,x.target_type,x.target_public_id,x.quantity,x.unit_price_snapshot,x.currency,x.commercial_total) for x in o.lines)
        return ObligationHandoff(t,'restaurant_order',o.public_id,o.mode_code,o.party_public_id,next(iter(currencies)),lines,sum((x.commercial_amount for x in lines),Decimal('0')))
