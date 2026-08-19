from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class R2Error(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable;super().__init__(code)

class R2Repository(Protocol):
    def define_section(self,c,p,fp)->MenuSection|None: ...
    def section(self,t,p)->MenuSection|None: ...
    def place_menu_entry(self,c,fp)->MenuSectionEntry|None: ...
    def bind_menu_entry_modifier_group(self,c,fp)->MenuEntryModifierBinding|None: ...
    def define_modifier_group(self,c,p,fp)->ModifierGroup|None: ...
    def modifier_group(self,t,p)->ModifierGroup|None: ...
    def add_modifier_option(self,c,p,price_amount,currency,fp)->ModifierOption|None: ...
    def modifier_option(self,t,p)->ModifierOption|None: ...
    def allowed_modifier_groups_for_line(self,t,line_public_id,at)->tuple[ModifierGroup,...]: ...
    def set_line_modifiers(self,c,p,normalized,fp)->ModifierSelectionSet|None: ...
    def modifier_set(self,t,line_public_id)->ModifierSelectionSet|None: ...
    def profile_station(self,c,p,fp)->StationProfile|None: ...
    def station(self,t,resource_public_id)->StationProfile|None: ...
    def define_route(self,c,p,fp)->RoutingRule|None: ...
    def routes_for_line(self,t,line,order,at)->tuple[RoutingRule,...]: ...
    def define_preparation_spec(self,c,p,fp)->PreparationSpec|None: ...
    def preparation_spec(self,t,p)->PreparationSpec|None: ...
    def release_preparation(self,c,plans,fp)->tuple[PreparationTicket,...]|None: ...
    def ticket(self,t,p)->PreparationTicket|None: ...
    def ticket_item(self,t,p)->PreparationTicketItem|None: ...
    def fire_ticket(self,c,fp)->PreparationTicket|None: ...
    def advance_ticket_item(self,c,fp)->PreparationTicketItem|None: ...
    def complete_ticket(self,c,fp)->PreparationTicket|None: ...
    def start_preparation_run(self,c,p,inputs,fp)->PreparationRun|None: ...
    def preparation_run(self,t,p)->PreparationRun|None: ...
    def complete_preparation_run(self,c,fp)->PreparationRun|None: ...

class R2Authority:
    def __init__(self,repo:R2Repository,*,catalog_resolver:Callable,catalog_entry_resolver:Callable,atomic_unit_resolver:Callable,offer_resolver:Callable,price_resolver:Callable,resource_resolver:Callable,order_resolver:Callable,order_line_resolver:Callable,party_resolver:Callable,authorize:Callable,semantic_matcher:Callable|None=None,public_id_factory:Callable[[],UUID]=uuid4):
        self.repo=repo;self.catalog_resolver=catalog_resolver;self.catalog_entry_resolver=catalog_entry_resolver;self.atomic_unit_resolver=atomic_unit_resolver;self.offer_resolver=offer_resolver;self.price_resolver=price_resolver;self.resource_resolver=resource_resolver;self.order_resolver=order_resolver;self.order_line_resolver=order_line_resolver;self.party_resolver=party_resolver;self.authorize=authorize;self.semantic_matcher=semantic_matcher or (lambda tenant_id,target_type,target_public_id,semantic_reference,at:False);self.public_id_factory=public_id_factory
    @staticmethod
    def _fp(c):return hashlib.sha256(json.dumps(asdict(c),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    @staticmethod
    def _code(v,f):
        v=v.strip().lower()
        if not v or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789._-' for ch in v):raise R2Error('R2_INVALID_'+f.upper(),'validation_failure',f+' must be a neutral code')
        return v
    @staticmethod
    def _aware(v,f):
        if v.tzinfo is None or v.utcoffset() is None:raise R2Error('R2_NAIVE_DATETIME','validation_failure',f+' must be timezone-aware')
        return v.astimezone(timezone.utc)
    @staticmethod
    def _qty(v):
        q=Decimal(v)
        if not q.is_finite() or q<=0:raise R2Error('R2_INVALID_QUANTITY','validation_failure','quantity must be positive')
        return q
    def _permit(self,t,p):
        if not self.authorize(t,p,'tenant',t):raise R2Error('R2_PERMISSION_DENIED','permission_denied','Restaurant menu/fulfillment operation is not permitted')
    @staticmethod
    def _station_owned(v,t,p,code):
        if v is None or getattr(v,'tenant_id',None)!=t or UUID(str(getattr(v,'resource_public_id',UUID(int=0))))!=p:raise R2Error(code,'scope_mismatch','Restaurant station resource was not found in this tenant')
        return v
    @staticmethod
    def _owned(v,t,p,code):
        if v is None or getattr(v,'tenant_id',None)!=t or UUID(str(getattr(v,'public_id',UUID(int=0))))!=p:raise R2Error(code,'scope_mismatch','Referenced authority was not found in this tenant')
        return v
    def define_menu_section(self,c:DefineMenuSection):
        self._permit(c.tenant_id,'restaurant.menu.manage');self._owned(self.catalog_resolver(c.tenant_id,c.catalog_public_id),c.tenant_id,c.catalog_public_id,'R2_CATALOG_NOT_FOUND')
        code=self._code(c.section_code,'section_code');name=c.display_name.strip();start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if not name or (end and end<=start):raise R2Error('R2_SECTION_INVALID','validation_failure','Menu section name/window invalid')
        n=replace(c,section_code=code,display_name=name,effective_from=start,effective_to=end);r=self.repo.define_section(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R2Error('R2_SECTION_CONFLICT','conflict','Menu section conflict')
        return r
    def place_menu_entry(self,c:PlaceMenuEntry):
        self._permit(c.tenant_id,'restaurant.menu.manage');section=self._owned(self.repo.section(c.tenant_id,c.section_public_id),c.tenant_id,c.section_public_id,'R2_SECTION_NOT_FOUND');entry=self._owned(self.catalog_entry_resolver(c.tenant_id,c.catalog_entry_public_id),c.tenant_id,c.catalog_entry_public_id,'R2_CATALOG_ENTRY_NOT_FOUND')
        entry_catalog=getattr(entry,'catalog_public_id',None)
        if entry_catalog is not None and UUID(str(entry_catalog))!=section.catalog_public_id:raise R2Error('R2_MENU_ENTRY_CATALOG_MISMATCH','scope_mismatch','Menu section and SO1 catalog entry must belong to the same catalog')
        start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if end and end<=start:raise R2Error('R2_MENU_ENTRY_WINDOW','validation_failure','Menu entry placement effective window invalid')
        n=replace(c,effective_from=start,effective_to=end);r=self.repo.place_menu_entry(n,self._fp(n))
        if r is None:raise R2Error('R2_MENU_ENTRY_CONFLICT','conflict','Menu entry placement conflict')
        return r
    def bind_menu_entry_modifier_group(self,c:BindMenuEntryModifierGroup):
        self._permit(c.tenant_id,'restaurant.modifier.manage');self._owned(self.catalog_entry_resolver(c.tenant_id,c.catalog_entry_public_id),c.tenant_id,c.catalog_entry_public_id,'R2_CATALOG_ENTRY_NOT_FOUND');self._owned(self.repo.modifier_group(c.tenant_id,c.modifier_group_public_id),c.tenant_id,c.modifier_group_public_id,'R2_MODIFIER_GROUP_NOT_FOUND')
        start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if end and end<=start:raise R2Error('R2_MODIFIER_BINDING_WINDOW','validation_failure','Modifier binding effective window invalid')
        n=replace(c,effective_from=start,effective_to=end);r=self.repo.bind_menu_entry_modifier_group(n,self._fp(n))
        if r is None:raise R2Error('R2_MODIFIER_BINDING_CONFLICT','conflict','Modifier binding conflict')
        return r
    def define_modifier_group(self,c:DefineModifierGroup):
        self._permit(c.tenant_id,'restaurant.modifier.manage');code=self._code(c.group_code,'group_code');name=c.display_name.strip();start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if not name or c.minimum_selections<0 or c.maximum_selections<1 or c.maximum_selections<c.minimum_selections:raise R2Error('R2_MODIFIER_GROUP_INVALID','validation_failure','Modifier group selection bounds invalid')
        if c.selection_mode is SelectionMode.SINGLE and c.maximum_selections!=1:raise R2Error('R2_SINGLE_GROUP_MAX_ONE','validation_failure','Single modifier group maximum must be one')
        if end and end<=start:raise R2Error('R2_MODIFIER_GROUP_WINDOW','validation_failure','Modifier group effective window invalid')
        n=replace(c,group_code=code,display_name=name,effective_from=start,effective_to=end);r=self.repo.define_modifier_group(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R2Error('R2_MODIFIER_GROUP_CONFLICT','conflict','Modifier group conflict')
        return r
    def add_modifier_option(self,c:AddModifierOption):
        self._permit(c.tenant_id,'restaurant.modifier.manage');g=self._owned(self.repo.modifier_group(c.tenant_id,c.group_public_id),c.tenant_id,c.group_public_id,'R2_MODIFIER_GROUP_NOT_FOUND')
        code=self._code(c.option_code,'option_code');name=c.display_name.strip();q=self._qty(c.default_quantity)
        if not name:raise R2Error('R2_MODIFIER_OPTION_NAME','validation_failure','Modifier option name required')
        if c.effect_type is not ModifierEffect.INSTRUCTION and (c.target_type is None or c.target_public_id is None):raise R2Error('R2_MODIFIER_TARGET_REQUIRED','validation_failure','Operational modifier target required')
        if c.effect_type is ModifierEffect.INSTRUCTION and c.target_type is None and not (c.preparation_instruction or '').strip():raise R2Error('R2_INSTRUCTION_REQUIRED','validation_failure','Instruction modifier requires text when no target is supplied')
        if c.target_public_id:
            resolver=self.atomic_unit_resolver if c.target_type is TargetType.ATOMIC_UNIT else self.offer_resolver
            self._owned(resolver(c.tenant_id,c.target_public_id),c.tenant_id,c.target_public_id,'R2_MODIFIER_TARGET_NOT_FOUND')
        price_amount=Decimal('0');currency=None
        if c.price_public_id and c.target_public_id is None:raise R2Error('R2_MODIFIER_PRICE_REQUIRES_TARGET','validation_failure','Priced modifier requires an SO1 target')
        if c.price_public_id:
            p=self._owned(self.price_resolver(c.tenant_id,c.price_public_id),c.tenant_id,c.price_public_id,'R2_MODIFIER_PRICE_NOT_FOUND');price_amount=Decimal(getattr(p,'amount'));currency=str(getattr(p,'currency')).upper()
            if c.target_public_id and UUID(str(getattr(p,'target_public_id',UUID(int=0))))!=c.target_public_id:raise R2Error('R2_MODIFIER_PRICE_TARGET_MISMATCH','scope_mismatch','Modifier price must price its SO1 target')
        n=replace(c,option_code=code,display_name=name,default_quantity=q,preparation_instruction=(c.preparation_instruction.strip() if c.preparation_instruction else None));r=self.repo.add_modifier_option(n,self.public_id_factory(),price_amount,currency,self._fp(n))
        if r is None:raise R2Error('R2_MODIFIER_OPTION_CONFLICT','conflict','Modifier option conflict')
        return r
    def set_line_modifiers(self,c:SetLineModifiers):
        self._permit(c.tenant_id,'restaurant.order.modifiers');line=self._owned(self.order_line_resolver(c.tenant_id,c.order_line_public_id),c.tenant_id,c.order_line_public_id,'R2_ORDER_LINE_NOT_FOUND');order=self._owned(self.order_resolver(c.tenant_id,getattr(line,'order_public_id')),c.tenant_id,getattr(line,'order_public_id'),'R2_ORDER_NOT_FOUND')
        status=getattr(getattr(order,'status',None),'value',getattr(order,'status',None));at=self._aware(c.occurred_at,'occurred_at')
        if status!='open':raise R2Error('R2_MODIFIERS_ORDER_NOT_OPEN','invalid_state_transition','Modifiers may change only while the R1 order is open')
        allowed={g.public_id:g for g in self.repo.allowed_modifier_groups_for_line(c.tenant_id,c.order_line_public_id,at)};grouped={};normalized=[]
        for x in c.selections:
            option=self._owned(self.repo.modifier_option(c.tenant_id,x.option_public_id),c.tenant_id,x.option_public_id,'R2_MODIFIER_OPTION_NOT_FOUND');gid=option.group_public_id
            if gid!=x.group_public_id or gid not in allowed:raise R2Error('R2_MODIFIER_NOT_ALLOWED','scope_mismatch','Modifier is not allowed for this menu line')
            q=self._qty(x.quantity);grouped.setdefault(gid,[]).append((option,q));normalized.append(replace(x,quantity=q))
        for gid,g in allowed.items():
            selections=grouped.get(gid,[]);count=sum((int(q) if g.selection_mode is SelectionMode.QUANTITY else 1 for _,q in selections),0)
            if count<g.minimum_selections or count>g.maximum_selections:raise R2Error('R2_MODIFIER_CARDINALITY','validation_failure','Modifier selection violates group cardinality')
            if g.selection_mode is SelectionMode.SINGLE and len(selections)>1:raise R2Error('R2_MODIFIER_CARDINALITY','validation_failure','Single modifier group accepts one option')
        n=replace(c,selections=tuple(normalized),occurred_at=at)
        if c.created_by_party_public_id:self._owned(self.party_resolver(c.tenant_id,c.created_by_party_public_id),c.tenant_id,c.created_by_party_public_id,'R2_PARTY_NOT_FOUND')
        r=self.repo.set_line_modifiers(n,self.public_id_factory(),tuple(normalized),self._fp(n))
        if r is None:raise R2Error('R2_MODIFIER_SET_CONFLICT','conflict','Modifier selection conflict',retryable=True)
        return r
    def profile_station(self,c:ProfileStation):
        self._permit(c.tenant_id,'restaurant.station.manage');self._owned(self.resource_resolver(c.tenant_id,c.resource_public_id),c.tenant_id,c.resource_public_id,'R2_STATION_RESOURCE_NOT_FOUND')
        code=self._code(c.station_code,'station_code');name=c.display_name.strip();channel=self._code(c.output_channel_code,'output_channel_code') if c.output_channel_code else None
        if not name:raise R2Error('R2_STATION_NAME_REQUIRED','validation_failure','Station name required')
        n=replace(c,station_code=code,display_name=name,output_channel_code=channel,destination_reference=c.destination_reference.strip() if c.destination_reference else None);r=self.repo.profile_station(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R2Error('R2_STATION_CONFLICT','conflict','Station profile conflict')
        return r
    def define_routing_rule(self,c:DefineRoutingRule):
        self._permit(c.tenant_id,'restaurant.routing.manage');self._station_owned(self.repo.station(c.tenant_id,c.station_resource_public_id),c.tenant_id,c.station_resource_public_id,'R2_STATION_NOT_FOUND')
        code=self._code(c.rule_code,'rule_code');start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if bool(c.semantic_reference)==bool(c.target_public_id):raise R2Error('R2_ROUTE_TARGET_EXCLUSIVE','validation_failure','Routing rule needs exactly one target or semantic reference')
        if c.target_public_id and c.target_type is None:raise R2Error('R2_ROUTE_TARGET_TYPE_REQUIRED','validation_failure','Direct routing target requires a target type')
        if c.semantic_reference and c.target_type is not None:raise R2Error('R2_ROUTE_SEMANTIC_TARGET_TYPE','validation_failure','Semantic routing does not also declare a direct target type')
        if c.target_public_id:
            resolver=self.atomic_unit_resolver if c.target_type is TargetType.ATOMIC_UNIT else self.offer_resolver
            self._owned(resolver(c.tenant_id,c.target_public_id),c.tenant_id,c.target_public_id,'R2_ROUTE_TARGET_NOT_FOUND')
        if end and end<=start:raise R2Error('R2_ROUTE_WINDOW','validation_failure','Routing effective window invalid')
        n=replace(c,rule_code=code,effective_from=start,effective_to=end,service_mode_code=self._code(c.service_mode_code,'service_mode_code') if c.service_mode_code else None,source_channel_code=self._code(c.source_channel_code,'source_channel_code') if c.source_channel_code else None,course_code=self._code(c.course_code,'course_code') if c.course_code else None,semantic_reference=c.semantic_reference.strip() if c.semantic_reference else None);r=self.repo.define_route(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R2Error('R2_ROUTE_CONFLICT','conflict','Routing rule conflict')
        return r
    def define_preparation_spec(self,c:DefinePreparationSpec):
        self._permit(c.tenant_id,'restaurant.recipe.manage');self._owned(self.atomic_unit_resolver(c.tenant_id,c.output_atomic_unit_public_id),c.tenant_id,c.output_atomic_unit_public_id,'R2_OUTPUT_UNIT_NOT_FOUND')
        code=self._code(c.spec_code,'spec_code');name=c.display_name.strip();start=self._aware(c.effective_from,'effective_from');end=self._aware(c.effective_to,'effective_to') if c.effective_to else None
        if not name or c.spec_version<1 or c.yield_stock_units<1 or not c.components:raise R2Error('R2_PREP_SPEC_INVALID','validation_failure','Preparation spec requires name/version/yield/components')
        if end and end<=start:raise R2Error('R2_PREP_SPEC_WINDOW','validation_failure','Preparation spec effective window invalid')
        components=[]
        for x in c.components:
            if x.required_stock_units<1:raise R2Error('R2_PREP_COMPONENT_QUANTITY','validation_failure','Preparation component stock units must be positive')
            if x.component_type=='atomic_unit':
                if not x.atomic_unit_public_id or x.dependency_spec_public_id:raise R2Error('R2_PREP_COMPONENT_SHAPE','validation_failure','Atomic-unit component shape invalid')
                self._owned(self.atomic_unit_resolver(c.tenant_id,x.atomic_unit_public_id),c.tenant_id,x.atomic_unit_public_id,'R2_INGREDIENT_NOT_FOUND')
            elif x.component_type=='preparation_spec':
                if not x.dependency_spec_public_id or x.atomic_unit_public_id:raise R2Error('R2_PREP_COMPONENT_SHAPE','validation_failure','Sub-preparation component shape invalid')
                dep=self._owned(self.repo.preparation_spec(c.tenant_id,x.dependency_spec_public_id),c.tenant_id,x.dependency_spec_public_id,'R2_DEPENDENCY_SPEC_NOT_FOUND')
                if dep.spec_code==code and dep.spec_version==c.spec_version:raise R2Error('R2_PREP_SELF_DEPENDENCY','validation_failure','Preparation spec cannot depend on itself')
            else:raise R2Error('R2_PREP_COMPONENT_TYPE','validation_failure','Unknown preparation component type')
            components.append(x)
        n=replace(c,spec_code=code,display_name=name,effective_from=start,effective_to=end,components=tuple(components));r=self.repo.define_preparation_spec(n,self.public_id_factory(),self._fp(n))
        if r is None:raise R2Error('R2_PREP_SPEC_CONFLICT','conflict','Preparation spec conflict')
        return r
    def release_preparation(self,c:ReleasePreparation):
        self._permit(c.tenant_id,'restaurant.ticket.release');order=self._owned(self.order_resolver(c.tenant_id,c.order_public_id),c.tenant_id,c.order_public_id,'R2_ORDER_NOT_FOUND');status=getattr(getattr(order,'status',None),'value',getattr(order,'status',None))
        if status!='submitted':raise R2Error('R2_ORDER_NOT_SUBMITTED','invalid_state_transition','Submitted R1 order required for preparation release')
        at=self._aware(c.occurred_at,'occurred_at');course=self._code(c.course_code,'course_code') if c.course_code else None;plans=[]
        selected=tuple(dict.fromkeys(c.line_public_ids))
        if len(selected)!=len(c.line_public_ids):raise R2Error('R2_DUPLICATE_RELEASE_LINE','validation_failure','Preparation release line selection contains duplicates')
        order_lines=tuple(getattr(order,'lines',()))
        if selected:
            by_id={line.public_id:line for line in order_lines}
            if any(p not in by_id for p in selected):raise R2Error('R2_RELEASE_LINE_NOT_IN_ORDER','scope_mismatch','Selected preparation line does not belong to this order')
            order_lines=tuple(by_id[p] for p in selected)
        for line in order_lines:
            routes=self.repo.routes_for_line(c.tenant_id,line,order,at)
            line_type=getattr(getattr(line,'target_type',None),'value',getattr(line,'target_type',None))
            routes=tuple(r for r in routes if (r.target_public_id==line.target_public_id) or (r.semantic_reference is not None and self.semantic_matcher(c.tenant_id,line_type,line.target_public_id,r.semantic_reference,at)))
            if course:routes=tuple(r for r in routes if r.course_code in (None,course))
            unique_routes={}
            for route in routes:unique_routes.setdefault((route.station_resource_public_id,route.course_code or course),route)
            routes=tuple(unique_routes.values())
            if not routes:raise R2Error('R2_NO_PREPARATION_ROUTE','invalid_state_transition','Every released order line requires a preparation route')
            modifier_set=self.repo.modifier_set(c.tenant_id,line.public_id)
            for route in routes:plans.append({'line':line,'route':route,'modifier_set':modifier_set})
        if not plans:raise R2Error('R2_NO_PREPARATION_LINES','invalid_state_transition','Order has no preparation lines')
        n=replace(c,occurred_at=at,course_code=course,line_public_ids=selected);r=self.repo.release_preparation(n,tuple(plans),self._fp(n))
        if r is None:raise R2Error('R2_RELEASE_CONFLICT','conflict','Preparation release conflict',retryable=True)
        return r
    def fire_ticket(self,c:FireTicket):
        self._permit(c.tenant_id,'restaurant.ticket.advance');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.fire_ticket(n,self._fp(n))
        if r is None:raise R2Error('R2_TICKET_STATE_CONFLICT','stale_version','Ticket cannot be fired',retryable=True)
        return r
    def advance_ticket_item(self,c:AdvanceTicketItem):
        self._permit(c.tenant_id,'restaurant.ticket.advance')
        if c.to_status not in {TicketItemStatus.IN_PROGRESS,TicketItemStatus.READY,TicketItemStatus.COMPLETED,TicketItemStatus.VOIDED}:raise R2Error('R2_ITEM_TRANSITION_INVALID','invalid_state_transition','Unsupported ticket item transition')
        n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.advance_ticket_item(n,self._fp(n))
        if r is None:raise R2Error('R2_TICKET_ITEM_STATE_CONFLICT','stale_version','Ticket item cannot advance',retryable=True)
        return r
    def complete_ticket(self,c:CompleteTicket):
        self._permit(c.tenant_id,'restaurant.ticket.advance');n=replace(c,occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.complete_ticket(n,self._fp(n))
        if r is None:raise R2Error('R2_TICKET_STATE_CONFLICT','stale_version','Ticket cannot complete',retryable=True)
        return r
    def start_preparation_run(self,c:StartPreparationRun):
        self._permit(c.tenant_id,'restaurant.preparation.run');spec=self._owned(self.repo.preparation_spec(c.tenant_id,c.preparation_spec_public_id),c.tenant_id,c.preparation_spec_public_id,'R2_PREP_SPEC_NOT_FOUND')
        if c.planned_output_units<1:raise R2Error('R2_PREP_OUTPUT_INVALID','validation_failure','Planned output units must be positive')
        factor=Decimal(c.planned_output_units)/Decimal(spec.yield_stock_units);inputs=[]
        for comp in spec.components:
            if comp.component_type=='atomic_unit':inputs.append(PreparationRunInput(comp.atomic_unit_public_id,max(1,int((Decimal(comp.required_stock_units)*factor).to_integral_value(rounding=ROUND_CEILING)))))
        n=replace(c,started_at=self._aware(c.started_at,'started_at'));r=self.repo.start_preparation_run(n,self.public_id_factory(),tuple(inputs),self._fp(n))
        if r is None:raise R2Error('R2_PREP_RUN_CONFLICT','conflict','Preparation run conflict',retryable=True)
        return r
    def complete_preparation_run(self,c:CompletePreparationRun):
        self._permit(c.tenant_id,'restaurant.preparation.run');run=self._owned(self.repo.preparation_run(c.tenant_id,c.preparation_run_public_id),c.tenant_id,c.preparation_run_public_id,'R2_PREP_RUN_NOT_FOUND')
        if run.status is not PrepRunStatus.IN_PROGRESS:raise R2Error('R2_PREP_RUN_STATE','invalid_state_transition','Preparation run is not in progress')
        if c.actual_output_units<0 or c.waste_output_units<0:raise R2Error('R2_PREP_RESULT_INVALID','validation_failure','Yield/waste cannot be negative')
        expected={x.atomic_unit_public_id:x for x in run.inputs};seen=set();inputs=[]
        for x in c.inputs:
            if x.atomic_unit_public_id not in expected or x.atomic_unit_public_id in seen:raise R2Error('R2_PREP_INPUT_INVALID','scope_mismatch','Actual preparation input is not part of this run')
            seen.add(x.atomic_unit_public_id)
            if x.consumed_stock_units is None or x.consumed_stock_units<0 or (x.waste_stock_units is not None and x.waste_stock_units<0):raise R2Error('R2_PREP_INPUT_INVALID','validation_failure','Consumed/waste stock units invalid')
            inputs.append(x)
        if set(expected)!=seen:raise R2Error('R2_PREP_INPUT_INCOMPLETE','validation_failure','All planned atomic inputs require actual evidence')
        n=replace(c,inputs=tuple(inputs),occurred_at=self._aware(c.occurred_at,'occurred_at'),reason_code=self._code(c.reason_code,'reason_code'));r=self.repo.complete_preparation_run(n,self._fp(n))
        if r is None:raise R2Error('R2_PREP_RUN_CONFLICT','stale_version','Preparation run changed',retryable=True)
        return r
    def inventory_handoff(self,t:int,run_public_id:UUID)->InventoryHandoff:
        self._permit(t,'restaurant.preparation.handoff.read');run=self._owned(self.repo.preparation_run(t,run_public_id),t,run_public_id,'R2_PREP_RUN_NOT_FOUND')
        if run.status is not PrepRunStatus.COMPLETED:raise R2Error('R2_PREP_RUN_NOT_COMPLETE','invalid_state_transition','Completed preparation run required')
        intents=[]
        for x in run.inputs:
            if x.consumed_stock_units:
                intents.append(StockIntent(x.atomic_unit_public_id,'issue',x.consumed_stock_units,'restaurant_preparation_input',str(run.public_id)))
        spec=self._owned(self.repo.preparation_spec(t,run.preparation_spec_public_id),t,run.preparation_spec_public_id,'R2_PREP_SPEC_NOT_FOUND')
        if run.actual_output_units:
            intents.append(StockIntent(spec.output_atomic_unit_public_id,'receipt',run.actual_output_units,'restaurant_preparation_output',str(run.public_id)))
        return InventoryHandoff(t,run.public_id,tuple(intents))
    def delivery_handoff(self,t:int,ticket_public_id:UUID)->DeliveryHandoff:
        self._permit(t,'restaurant.ticket.delivery.read');ticket=self._owned(self.repo.ticket(t,ticket_public_id),t,ticket_public_id,'R2_TICKET_NOT_FOUND');station=self._station_owned(self.repo.station(t,ticket.station_resource_public_id),t,ticket.station_resource_public_id,'R2_STATION_NOT_FOUND')
        if not station.output_channel_code or not station.destination_reference:raise R2Error('R2_STATION_NO_DELIVERY_ROUTE','invalid_state_transition','Station has no SO8 delivery route')
        payload={'ticket_public_id':str(ticket.public_id),'order_public_id':str(ticket.order_public_id),'station_resource_public_id':str(ticket.station_resource_public_id),'status':ticket.status.value,'course_code':ticket.course_code,'items':[{'item_public_id':str(x.public_id),'order_line_public_id':str(x.order_line_public_id),'quantity':str(x.quantity),'status':x.status.value,'preparation_note':x.preparation_note,'modifiers':list(x.modifier_snapshot)} for x in ticket.items]}
        return DeliveryHandoff(t,ticket.public_id,'restaurant_preparation_ticket',station.output_channel_code,station.destination_reference,payload)
