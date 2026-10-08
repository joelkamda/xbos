from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
import copy
from dataclasses import replace
import copy
from types import SimpleNamespace
from uuid import uuid4
import pytest
from restaurant.r2.contracts import *
from restaurant.r2.service import R2Authority,R2Error

class FakeRepo:
    def __init__(self):
        self.sections={};self.placements=[];self.bindings=[];self.groups={};self.options={};self.allowed={};self.modsets={};self.stations={};self.routes=[];self.specs={};self.tickets={};self.items={};self.runs={};self.line_states={}
    def define_section(self,c,p,fp):
        x=MenuSection(p,c.tenant_id,c.catalog_public_id,c.section_code,c.display_name,c.sort_order,c.effective_from,c.effective_to,True,c.metadata,1);self.sections[p]=x;return x
    def section(self,t,p):return self.sections.get(p)
    def menu_sections(self,t,catalog_public_id,at):
        return tuple(sorted((x for x in self.sections.values() if x.tenant_id==t and x.catalog_public_id==catalog_public_id and x.active and x.effective_from<=at and (x.effective_to is None or at<x.effective_to)),key=lambda x:(x.sort_order,x.section_code,str(x.public_id))))
    def menu_section_entries(self,t,section_public_id,at):
        return tuple(sorted((x for x in self.placements if x.tenant_id==t and x.section_public_id==section_public_id and x.effective_from<=at and (x.effective_to is None or at<x.effective_to)),key=lambda x:(x.sort_order,str(x.catalog_entry_public_id))))
    def place_menu_entry(self,c,fp):
        x=MenuSectionEntry(c.tenant_id,c.section_public_id,c.catalog_entry_public_id,c.sort_order,c.effective_from,c.effective_to);self.placements.append(x);return x
    def bind_menu_entry_modifier_group(self,c,fp):
        x=MenuEntryModifierBinding(c.tenant_id,c.catalog_entry_public_id,c.modifier_group_public_id,c.sequence,c.effective_from,c.effective_to);self.bindings.append(x);return x
    def define_modifier_group(self,c,p,fp):
        x=ModifierGroup(p,c.tenant_id,c.group_code,c.display_name,c.selection_mode,c.minimum_selections,c.maximum_selections,c.effective_from,c.effective_to,True,c.metadata,1);self.groups[p]=x;return x
    def modifier_group(self,t,p):return self.groups.get(p)
    def add_modifier_option(self,c,p,price_amount,currency,fp):
        x=ModifierOption(p,c.tenant_id,c.group_public_id,c.option_code,c.display_name,c.effect_type,c.target_type,c.target_public_id,c.price_public_id,c.default_quantity,c.preparation_instruction,True,c.sort_order,c.metadata);self.options[p]=x;return x
    def modifier_option(self,t,p):return self.options.get(p)
    def modifier_configuration(self,t,catalog_entry_public_id,at):
        rows=[]
        for b in self.bindings:
            g=self.groups.get(b.modifier_group_public_id)
            if b.tenant_id!=t or b.catalog_entry_public_id!=catalog_entry_public_id or not (b.effective_from<=at and (b.effective_to is None or at<b.effective_to)) or g is None or not g.active or not (g.effective_from<=at and (g.effective_to is None or at<g.effective_to)):continue
            opts=tuple(sorted((o for o in self.options.values() if o.tenant_id==t and o.group_public_id==g.public_id and o.active),key=lambda o:(o.sort_order,o.option_code,str(o.public_id))))
            rows.append(ModifierConfiguration(b.sequence,g,opts))
        return tuple(sorted(rows,key=lambda x:(x.sequence,x.group.group_code,str(x.group.public_id))))
    def allowed_modifier_groups_for_line(self,t,p,at):return tuple(self.allowed.get(p,()))
    def set_line_modifiers(self,c,p,normalized,fp):
        if self.line_states.get(c.order_line_public_id,'active')!='active':return None
        prior=self.modsets.get(c.order_line_public_id);v=1 if prior is None else prior.selection_version+1;x=ModifierSelectionSet(p,c.tenant_id,c.order_line_public_id,v,tuple(normalized),c.occurred_at);self.modsets[c.order_line_public_id]=x;return x
    def modifier_set(self,t,p):return self.modsets.get(p)
    def profile_station(self,c,p,fp):
        x=StationProfile(p,c.tenant_id,c.resource_public_id,c.station_code,c.display_name,c.station_kind,c.output_channel_code,c.destination_reference,True,c.metadata,1);self.stations[c.resource_public_id]=x;return x
    def station(self,t,p):return self.stations.get(p)
    def define_route(self,c,p,fp):
        x=RoutingRule(p,c.tenant_id,c.rule_code,c.station_resource_public_id,c.target_type,c.target_public_id,c.semantic_reference,c.service_mode_code,c.source_channel_code,c.course_code,c.priority,c.effective_from,c.effective_to,True,c.metadata);self.routes.append(x);return x
    def routes_for_line(self,t,line,order,at):
        return tuple(r for r in self.routes if r.tenant_id==t and (r.semantic_reference is not None or (r.target_type and r.target_public_id==line.target_public_id)) and (r.service_mode_code is None or r.service_mode_code==order.mode_code) and (r.source_channel_code is None or r.source_channel_code==order.source_channel_code))
    def define_preparation_spec(self,c,p,fp):
        x=PreparationSpec(p,c.tenant_id,c.spec_code,c.spec_version,c.display_name,c.output_atomic_unit_public_id,c.yield_stock_units,c.effective_from,c.effective_to,c.components,'active',c.metadata);self.specs[p]=x;return x
    def preparation_spec(self,t,p):return self.specs.get(p)
    def release_preparation(self,c,plans,fp):
        if any(self.line_states.get(plan['line'].public_id,'active')!='active' for plan in plans):return None
        grouped={}
        for plan in plans:grouped.setdefault(plan['route'].station_resource_public_id,[]).append(plan)
        out=[]
        for idx,(station,rows) in enumerate(grouped.items(),1):
            tp=uuid4();items=[]
            for plan in rows:
                ip=uuid4();ms=plan.get('modifier_set');snap=tuple({'group_public_id':str(s.group_public_id),'option_public_id':str(s.option_public_id),'quantity':str(s.quantity)} for s in (ms.selections if ms else ()))
                item=PreparationTicketItem(ip,c.tenant_id,tp,plan['line'].public_id,plan['line'].quantity,TicketItemStatus.HELD if c.hold else TicketItemStatus.QUEUED,ms.public_id if ms else None,plan['line'].note,snap,1);items.append(item);self.items[ip]=item
            ticket=PreparationTicket(tp,c.tenant_id,c.order_public_id,station,f'T{idx}',TicketStatus.HELD if c.hold else TicketStatus.QUEUED,c.course_code,100,c.hold,c.occurred_at,None,None,tuple(items),1);self.tickets[tp]=ticket;out.append(ticket)
        return tuple(out)
    def ticket(self,t,p):return self.tickets.get(p)
    def ticket_item(self,t,p):return self.items.get(p)
    def fire_ticket(self,c,fp):
        x=self.tickets.get(c.ticket_public_id)
        if not x or x.row_version!=c.expected_version or x.status is not TicketStatus.HELD:return None
        items=tuple(PreparationTicketItem(i.public_id,i.tenant_id,i.ticket_public_id,i.order_line_public_id,i.quantity,TicketItemStatus.QUEUED,i.modifier_set_public_id,i.preparation_note,i.modifier_snapshot,i.row_version+1) for i in x.items)
        for i in items:self.items[i.public_id]=i
        x=PreparationTicket(x.public_id,x.tenant_id,x.order_public_id,x.station_resource_public_id,x.ticket_code,TicketStatus.QUEUED,x.course_code,x.priority,False,x.released_at,c.occurred_at,None,items,x.row_version+1);self.tickets[x.public_id]=x;return x
    def advance_ticket_item(self,c,fp):
        x=self.items.get(c.ticket_item_public_id)
        if not x or x.row_version!=c.expected_version:return None
        x=PreparationTicketItem(x.public_id,x.tenant_id,x.ticket_public_id,x.order_line_public_id,x.quantity,c.to_status,x.modifier_set_public_id,x.preparation_note,x.modifier_snapshot,x.row_version+1);self.items[x.public_id]=x;return x
    def complete_ticket(self,c,fp):return None
    def start_preparation_run(self,c,p,inputs,fp):
        x=PreparationRun(p,c.tenant_id,c.preparation_spec_public_id,c.ticket_item_public_id,PrepRunStatus.IN_PROGRESS,c.planned_output_units,None,None,c.started_at,None,tuple(inputs),1);self.runs[p]=x;return x
    def preparation_run(self,t,p):return self.runs.get(p)
    def complete_preparation_run(self,c,fp):
        x=self.runs.get(c.preparation_run_public_id)
        if not x or x.row_version!=c.expected_version:return None
        x=PreparationRun(x.public_id,x.tenant_id,x.preparation_spec_public_id,x.ticket_item_public_id,PrepRunStatus.COMPLETED,x.planned_output_units,c.actual_output_units,c.waste_output_units,x.started_at,c.occurred_at,c.inputs if not c.inputs else c.inputs,x.row_version+1);self.runs[x.public_id]=x;return x

def obj(t,p,**kw):return SimpleNamespace(tenant_id=t,public_id=p,**kw)
def price_key(t,target_type,target_public_id,price_code,currency,scope_type,scope_id):
    return ('resolved_price',t,getattr(target_type,'value',target_type),target_public_id,price_code.lower(),currency.upper(),getattr(scope_type,'value',scope_type),scope_id)
def authority(semantic_matcher=None,authorize=lambda *a:True):
    repo=FakeRepo();store={}
    def resolver(t,p):return store.get((t,p))
    def resolve_price(q):return store.get(price_key(q.tenant_id,q.target_type,q.target_public_id,q.price_code,q.currency,q.scope_type,q.scope_id))
    a=R2Authority(repo,catalog_resolver=resolver,catalog_entry_resolver=resolver,atomic_unit_resolver=resolver,offer_resolver=resolver,price_resolver=resolver,resource_resolver=resolver,order_resolver=resolver,order_line_resolver=resolver,party_resolver=resolver,authorize=authorize,semantic_matcher=semantic_matcher,price_resolution_resolver=resolve_price)
    return a,repo,store

def test_menu_section_is_so1_projection_not_catalog_identity():
    a,_,s=authority();cat=uuid4();s[(1,cat)]=obj(1,cat);section=a.define_menu_section(DefineMenuSection('sec',1,cat,'mains','Mains',datetime.now(timezone.utc)));assert section.catalog_public_id==cat

def test_menu_section_places_only_so1_catalog_entries_and_modifier_binding_is_explicit():
    a,r,s=authority();cat=uuid4();entry=uuid4();s[(1,cat)]=obj(1,cat);s[(1,entry)]=obj(1,entry,catalog_public_id=cat);section=a.define_menu_section(DefineMenuSection('sec',1,cat,'mains','Mains',datetime.now(timezone.utc)));placed=a.place_menu_entry(PlaceMenuEntry('place',1,section.public_id,entry,datetime.now(timezone.utc),sort_order=10));group=a.define_modifier_group(DefineModifierGroup('g',1,'sides','Sides',SelectionMode.MULTIPLE,0,2,datetime.now(timezone.utc)));bound=a.bind_menu_entry_modifier_group(BindMenuEntryModifierGroup('bind',1,entry,group.public_id,datetime.now(timezone.utc)));assert placed.catalog_entry_public_id==entry and bound.modifier_group_public_id==group.public_id

def test_modifier_cardinality_and_so1_target_reference():
    a,r,s=authority();group=a.define_modifier_group(DefineModifierGroup('g',1,'doneness','Doneness',SelectionMode.SINGLE,1,1,datetime.now(timezone.utc)));target=uuid4();s[(1,target)]=obj(1,target);opt=a.add_modifier_option(AddModifierOption('o',1,group.public_id,'medium','Medium',ModifierEffect.INSTRUCTION,TargetType.ATOMIC_UNIT,target,preparation_instruction='medium'));line=uuid4();order=uuid4();s[(1,line)]=obj(1,line,order_public_id=order);s[(1,order)]=obj(1,order,status=SimpleNamespace(value='open'));r.allowed[line]=[group];result=a.set_line_modifiers(SetLineModifiers('set',1,line,(ModifierSelection(group.public_id,opt.public_id),),datetime.now(timezone.utc)));assert result.selection_version==1

def test_modifiers_cannot_change_after_order_submission():
    a,r,s=authority();line=uuid4();order=uuid4();s[(1,line)]=obj(1,line,order_public_id=order);s[(1,order)]=obj(1,order,status=SimpleNamespace(value='submitted'))
    with pytest.raises(R2Error) as e:a.set_line_modifiers(SetLineModifiers('set',1,line,(),datetime.now(timezone.utc)))
    assert e.value.code=='R2_MODIFIERS_ORDER_NOT_OPEN'

def test_station_is_so5_resource_and_delivery_neutral():
    a,_,s=authority();resource=uuid4();s[(1,resource)]=obj(1,resource);station=a.profile_station(ProfileStation('st',1,resource,'hot_line','Hot Line',StationKind.KITCHEN,'local_print','kitchen-1'));assert station.resource_public_id==resource and station.output_channel_code=='local_print'

def test_multi_station_fanout_and_hold_fire():
    a,r,s=authority();target=uuid4();s[(1,target)]=obj(1,target);orderp=uuid4();linep=uuid4();line=obj(1,linep,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,quantity=Decimal('1'),note=None);order=obj(1,orderp,status=SimpleNamespace(value='submitted'),mode_code='dine_in',source_channel_code='in_person',lines=(line,));s[(1,orderp)]=order
    resources=[uuid4(),uuid4()]
    for i,res in enumerate(resources):s[(1,res)]=obj(1,res);a.profile_station(ProfileStation(f's{i}',1,res,f's{i}',f'S{i}',StationKind.KITCHEN));a.define_routing_rule(DefineRoutingRule(f'r{i}',1,f'r{i}',res,datetime.now(timezone.utc),TargetType.ATOMIC_UNIT,target))
    tickets=a.release_preparation(ReleasePreparation('rel',1,orderp,datetime.now(timezone.utc),hold=True));assert len(tickets)==2 and all(t.status is TicketStatus.HELD for t in tickets)
    fired=a.fire_ticket(FireTicket('fire',1,tickets[0].public_id,1,datetime.now(timezone.utc)));assert fired.status is TicketStatus.QUEUED

def test_partial_course_release_can_select_order_lines_without_redefining_r1_order():
    a,r,s=authority();targets=[uuid4(),uuid4()];resources=[uuid4(),uuid4()]
    for target in targets:s[(1,target)]=obj(1,target)
    orderp=uuid4();lines=[]
    for target in targets:
        lp=uuid4();lines.append(obj(1,lp,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,quantity=Decimal('1'),note=None))
    order=obj(1,orderp,status=SimpleNamespace(value='submitted'),mode_code='dine_in',source_channel_code='in_person',lines=tuple(lines));s[(1,orderp)]=order
    for i,(target,res) in enumerate(zip(targets,resources)):
        s[(1,res)]=obj(1,res);a.profile_station(ProfileStation(f's{i}',1,res,f's{i}',f'S{i}',StationKind.KITCHEN));a.define_routing_rule(DefineRoutingRule(f'r{i}',1,f'r{i}',res,datetime.now(timezone.utc),TargetType.ATOMIC_UNIT,target,course_code='main' if i else 'starter'))
    tickets=a.release_preparation(ReleasePreparation('starter-release',1,orderp,datetime.now(timezone.utc),course_code='starter',line_public_ids=(lines[0].public_id,)));assert len(tickets)==1 and tickets[0].items[0].order_line_public_id==lines[0].public_id

def test_semantic_routing_can_consume_sc41_classification_without_owning_it():
    matcher=lambda tenant,target_type,target,semantic,at: semantic=='commerce.food.hot'
    a,r,s=authority(matcher);target=uuid4();s[(1,target)]=obj(1,target);orderp=uuid4();linep=uuid4();line=obj(1,linep,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,quantity=Decimal('1'),note=None);order=obj(1,orderp,status=SimpleNamespace(value='submitted'),mode_code='dine_in',source_channel_code='in_person',lines=(line,));s[(1,orderp)]=order;resource=uuid4();s[(1,resource)]=obj(1,resource);a.profile_station(ProfileStation('st',1,resource,'hot','Hot',StationKind.KITCHEN));a.define_routing_rule(DefineRoutingRule('sem',1,'hot_food',resource,datetime.now(timezone.utc),semantic_reference='commerce.food.hot'));tickets=a.release_preparation(ReleasePreparation('rel-sem',1,orderp,datetime.now(timezone.utc)));assert len(tickets)==1 and tickets[0].station_resource_public_id==resource

def test_preparation_spec_yield_waste_produces_so3_intent_not_stock_write():
    a,r,s=authority();out=uuid4();ingredient=uuid4();s[(1,out)]=obj(1,out);s[(1,ingredient)]=obj(1,ingredient);spec=a.define_preparation_spec(DefinePreparationSpec('spec',1,'tomato_sauce',1,'Tomato Sauce',out,10,datetime.now(timezone.utc),(PreparationComponent('atomic_unit',ingredient,None,20),)));run=a.start_preparation_run(StartPreparationRun('run',1,spec.public_id,20,datetime.now(timezone.utc)));assert run.inputs[0].planned_stock_units==40
    completed=a.complete_preparation_run(CompletePreparationRun('done',1,run.public_id,1,18,2,(PreparationRunInput(ingredient,40,38,2),),datetime.now(timezone.utc)));handoff=a.inventory_handoff(1,completed.public_id);assert handoff.authority=='SO3' and handoff.creates_inventory_truth is False and {i.movement_kind for i in handoff.intents}=={'issue','receipt'}

def test_delivery_handoff_does_not_create_so8_job():
    a,r,s=authority();resource=uuid4();s[(1,resource)]=obj(1,resource);a.profile_station(ProfileStation('st',1,resource,'expo','Expo',StationKind.EXPO,'kds','expo-screen'));ticketp=uuid4();orderp=uuid4();r.tickets[ticketp]=PreparationTicket(ticketp,1,orderp,resource,'T1',TicketStatus.QUEUED,None,100,False,datetime.now(timezone.utc),items=());h=a.delivery_handoff(1,ticketp);assert h.authority=='SO8' and h.creates_delivery_job is False and h.destination_reference=='expo-screen'

def test_sql_forbids_duplicate_inventory_delivery_finance_writers():
    root=Path(__file__).resolve().parents[2];up=(root/'alembic_neutral/sql/r2_restaurant_menu_fulfillment_up.sql').read_text(encoding='utf-8').lower()
    assert 'insert into public.inventory_movements' not in up and 'insert into public.so8_delivery_jobs' not in up and 'insert into public.financial_events' not in up

def test_ticket_item_progress_rolls_up_parent_partial_readiness():
    root=Path(__file__).resolve().parents[2];repo=(root/'restaurant/r2/sql_repository.py').read_text(encoding='utf-8');assert "new_status='partially_ready'" in repo and 'item_rollup' in repo

def test_preparation_release_replay_is_scoped_to_release_command():
    root=Path(__file__).resolve().parents[2];up=(root/'alembic_neutral/sql/r2_restaurant_menu_fulfillment_up.sql').read_text(encoding='utf-8');repo=(root/'restaurant/r2/sql_repository.py').read_text(encoding='utf-8');assert 'release_command_key varchar(180) NOT NULL' in up and 'WHERE tenant_id=:t AND release_command_key=:k' in repo and 'uuid4()' in repo

def test_r2_migration_is_linear_child_of_r1():
    root=Path(__file__).resolve().parents[2];v=(root/'alembic_neutral/versions/r2_restaurant_menu_fulfillment_043.py').read_text(encoding='utf-8');assert "revision='r2_restaurant_menu_fulfillment_043'" in v and "down_revision='r1_restaurant_service_operation_042'" in v

def test_r2_pc0_extension_is_authorized_as_pack_descendant():
    import json
    root=Path(__file__).resolve().parents[2];d=json.loads((root/'contracts/platform/v1/pc0_frozen_finance_inventory.json').read_text());paths={x['path']:x for x in d['authorized_non_finance_extensions']}
    assert paths['versions/r2_restaurant_menu_fulfillment_043.py']['owner']=='PK'

def test_acceptance_scopes_both_database_environment_authorities():
    root=Path(__file__).resolve().parents[2];source=(root/'scripts/verify_r2_restaurant_menu_fulfillment.py').read_text(encoding='utf-8');assert "('DATABASE_URL','MIGRATION_DATABASE_URL')" in source and "url.replace('%','%%')" in source

def _menu_fixture(*,authorize=lambda *a:True):
    a,r,s=authority(authorize=authorize);now=datetime(2026,9,19,9,0,tzinfo=timezone.utc);cat=uuid4();entry=uuid4();target=uuid4();price=uuid4()
    s[(1,cat)]=obj(1,cat,active=True,effective_from=now,effective_to=None,code='main_menu',name='Menu')
    s[(1,entry)]=obj(1,entry,catalog_public_id=cat,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,enabled=True,effective_from=now,effective_to=None)
    s[(1,target)]=obj(1,target,active=True,code='item_one',name='Item One')
    main_price=obj(1,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,price_code='retail',amount=Decimal('4500'),currency='XAF',scope_type=SimpleNamespace(value='tenant'),scope_id=None,effective_from=now,effective_to=None,active=True)
    s[price_key(1,'atomic_unit',target,'retail','XAF','tenant',None)]=main_price
    sec=a.define_menu_section(DefineMenuSection('sec',1,cat,'mains','Mains',now,sort_order=20))
    a.place_menu_entry(PlaceMenuEntry('place',1,sec.public_id,entry,now,sort_order=10))
    return a,r,s,now,cat,entry,target,main_price

def test_public_menu_composes_r2_placement_with_so1_identity_price_and_modifiers():
    a,r,s,now,cat,entry,target,main_price=_menu_fixture()
    group=a.define_modifier_group(DefineModifierGroup('g',1,'spice','Spice',SelectionMode.SINGLE,0,1,now))
    extra_target=uuid4();extra_price_id=uuid4();s[(1,extra_target)]=obj(1,extra_target,active=True,code='extra',name='Extra')
    extra_price=obj(1,extra_price_id,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=extra_target,price_code='modifier',amount=Decimal('250'),currency='XAF',scope_type=SimpleNamespace(value='tenant'),scope_id=None,effective_from=now,effective_to=None,active=True)
    s[(1,extra_price_id)]=extra_price
    option=a.add_modifier_option(AddModifierOption('o',1,group.public_id,'extra','Extra',ModifierEffect.ADD,TargetType.ATOMIC_UNIT,extra_target,extra_price_id,Decimal('1'),sort_order=2))
    a.bind_menu_entry_modifier_group(BindMenuEntryModifierGroup('b',1,entry,group.public_id,now,sequence=3))
    menu=a.menu(1,cat,now,'retail','xaf','tenant',None)
    assert menu.catalog_reference.public_id==cat and menu.pricing_context.currency=='XAF' and menu.creates_financial_truth is False
    item=menu.sections[0].entries[0]
    assert item.catalog_entry_public_id==entry and item.target_public_id==target and item.target_presentation.name=='Item One'
    assert item.resolved_price is main_price and item.resolved_price.amount==Decimal('4500')
    cfg=item.modifier_configuration[0]
    assert cfg.group_public_id==group.public_id and cfg.selection_mode is SelectionMode.SINGLE and cfg.sequence==3
    assert cfg.options[0].option_public_id==option.public_id and cfg.options[0].price_effect.amount==Decimal('250')

def test_menu_sections_and_modifier_configuration_are_public_tenant_scoped_reads():
    a,r,s,now,cat,entry,target,price=_menu_fixture()
    group=a.define_modifier_group(DefineModifierGroup('g',1,'choice','Choice',SelectionMode.SINGLE,0,1,now))
    option=a.add_modifier_option(AddModifierOption('o',1,group.public_id,'plain','Plain',ModifierEffect.INSTRUCTION,preparation_instruction='plain'))
    a.bind_menu_entry_modifier_group(BindMenuEntryModifierGroup('b',1,entry,group.public_id,now,sequence=1))
    sections=a.menu_sections(1,cat,now);cfg=a.modifier_configuration(1,entry,now,'XAF','tenant',None)
    assert len(sections)==1 and sections[0].tenant_id==1
    assert len(cfg)==1 and cfg[0].group_public_id==group.public_id and cfg[0].options[0].option_public_id==option.public_id

def test_menu_authorization_fails_closed_before_any_result():
    a,r,s,now,cat,entry,target,price=_menu_fixture(authorize=lambda t,p,*_:p!='restaurant.menu.read')
    before=copy.deepcopy((r.sections,r.placements,r.bindings,r.groups,r.options))
    with pytest.raises(R2Error) as e:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert e.value.code=='R2_PERMISSION_DENIED'
    assert before==copy.deepcopy((r.sections,r.placements,r.bindings,r.groups,r.options))

def test_menu_cross_catalog_placement_fails_closed_and_cross_tenant_is_not_disclosed():
    a,r,s,now,cat,entry,target,price=_menu_fixture()
    other=uuid4();s[(1,other)]=obj(1,other,active=True,effective_from=now,effective_to=None)
    s[(1,entry)].catalog_public_id=other
    with pytest.raises(R2Error) as e:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert e.value.code=='R2_MENU_ENTRY_CATALOG_MISMATCH'
    s[(1,entry)].catalog_public_id=cat
    del s[(1,cat)];s[(2,cat)]=obj(2,cat,active=True,effective_from=now,effective_to=None)
    with pytest.raises(R2Error) as cross:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert cross.value.code=='R2_CATALOG_NOT_FOUND'

def test_menu_filters_inactive_and_expired_rows_and_sorts_deterministically():
    a,r,s,now,cat,entry,target,price=_menu_fixture()
    sec2=a.define_menu_section(DefineMenuSection('s2',1,cat,'starters','Starters',now,sort_order=5))
    e2=uuid4();t2=uuid4();p2=uuid4();s[(1,e2)]=obj(1,e2,catalog_public_id=cat,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=t2,enabled=True,effective_from=now,effective_to=None);s[(1,t2)]=obj(1,t2,active=True,name='Starter')
    s[price_key(1,'atomic_unit',t2,'retail','XAF','tenant',None)]=obj(1,p2,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=t2,price_code='retail',amount=Decimal('1000'),currency='XAF',scope_type=SimpleNamespace(value='tenant'),scope_id=None,effective_from=now,effective_to=None,active=True)
    a.place_menu_entry(PlaceMenuEntry('p2',1,sec2.public_id,e2,now,sort_order=1))
    a.define_menu_section(DefineMenuSection('sx',1,cat,'old','Old',now.replace(day=18),effective_to=now,sort_order=0))
    inactive=a.define_menu_section(DefineMenuSection('si',1,cat,'inactive','Inactive',now,sort_order=0));r.sections[inactive.public_id]=replace(r.sections[inactive.public_id],active=False)
    menu=a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert [x.section_code for x in menu.sections]==['starters','mains']
    s[(1,e2)].enabled=False
    menu=a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert menu.sections[0].entries==()

def test_menu_price_target_scope_and_currency_mismatches_fail_closed():
    a,r,s,now,cat,entry,target,price=_menu_fixture();key=price_key(1,'atomic_unit',target,'retail','XAF','tenant',None);original=s[key]
    s[key]=obj(1,original.public_id,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=uuid4(),price_code='retail',amount=Decimal('4500'),currency='XAF',scope_type=SimpleNamespace(value='tenant'),scope_id=None,effective_from=now,effective_to=None,active=True)
    with pytest.raises(R2Error) as e:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert e.value.code=='R2_PRICE_TARGET_MISMATCH'
    s[key]=obj(1,original.public_id,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,price_code='retail',amount=Decimal('4500'),currency='USD',scope_type=SimpleNamespace(value='tenant'),scope_id=None,effective_from=now,effective_to=None,active=True)
    with pytest.raises(R2Error) as c:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert c.value.code=='R2_PRICE_CURRENCY_MISMATCH'
    s[key]=obj(1,original.public_id,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,price_code='retail',amount=Decimal('4500'),currency='XAF',scope_type=SimpleNamespace(value='location'),scope_id=9,effective_from=now,effective_to=None,active=True)
    with pytest.raises(R2Error) as scope:a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert scope.value.code=='R2_PRICE_SCOPE_MISMATCH'

def test_menu_read_is_side_effect_free_and_reuses_public_so1_objects():
    a,r,s,now,cat,entry,target,price=_menu_fixture();before=copy.deepcopy((r.sections,r.placements,r.bindings,r.groups,r.options,r.modsets))
    menu=a.menu(1,cat,now,'retail','XAF','tenant',None)
    assert menu.catalog_reference is s[(1,cat)]
    assert menu.sections[0].entries[0].target_presentation is s[(1,target)]
    assert before==copy.deepcopy((r.sections,r.placements,r.bindings,r.groups,r.options,r.modsets))

def test_r3_menu_surface_has_no_private_so1_import_no_wnd_hardcoding_and_no_finance_writer():
    root=Path(__file__).resolve().parents[2]
    service=(root/'restaurant/r2/service.py').read_text(encoding='utf-8').lower();repo=(root/'restaurant/r2/sql_repository.py').read_text(encoding='utf-8').lower()
    assert 'shared_operations.so1.sql_repository' not in service
    assert 'wnd' not in service and 'wnd' not in repo
    assert 'insert into public.financial_' not in repo and 'insert into public.payment_' not in repo

def test_removed_r1_line_denies_new_modifier_and_preparation_mutation_but_preserves_history():
    a,r,s=authority();line=uuid4();order=uuid4();target=uuid4();resource=uuid4();s[(1,line)]=obj(1,line,order_public_id=order,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,quantity=Decimal('1'),note=None);s[(1,order)]=obj(1,order,status=SimpleNamespace(value='open'),mode_code='dine_in',source_channel_code='in_person',lines=(s[(1,line)],));r.line_states[line]='removed';prior=ModifierSelectionSet(uuid4(),1,line,1,(),datetime.now(timezone.utc));r.modsets[line]=prior
    with pytest.raises(R2Error) as mod:a.set_line_modifiers(SetLineModifiers('set-removed',1,line,(),datetime.now(timezone.utc)));assert mod.value.code=='R2_MODIFIER_SET_CONFLICT';assert r.modsets[line] is prior
    s[(1,order)].status=SimpleNamespace(value='submitted');s[(1,target)]=obj(1,target);s[(1,resource)]=obj(1,resource);a.profile_station(ProfileStation('st',1,resource,'hot','Hot',StationKind.KITCHEN));a.define_routing_rule(DefineRoutingRule('rr',1,'hot',resource,datetime.now(timezone.utc),TargetType.ATOMIC_UNIT,target))
    existing_ticket=PreparationTicket(uuid4(),1,order,resource,'OLD',TicketStatus.COMPLETED,None,100,False,datetime.now(timezone.utc),items=());r.tickets[existing_ticket.public_id]=existing_ticket
    with pytest.raises(R2Error) as prep:a.release_preparation(ReleasePreparation('rel-removed',1,order,datetime.now(timezone.utc),line_public_ids=(line,)));assert prep.value.code=='R2_RELEASE_CONFLICT';assert r.tickets[existing_ticket.public_id] is existing_ticket

def test_c2_r2_sql_guards_non_active_lines_without_filtering_historical_reads():
    root=Path(__file__).resolve().parents[2];repo=(root/'restaurant/r2/sql_repository.py').read_text(encoding='utf-8');mod=repo[repo.index('def set_line_modifiers'):repo.index('def modifier_set',repo.index('def set_line_modifiers'))];rel=repo[repo.index('def release_preparation'):repo.index('def ticket',repo.index('def release_preparation'))];hist=repo[repo.index('def modifier_set'):repo.index('def _station',repo.index('def modifier_set'))]
    assert 'line_lifecycle_status' in mod and "!='active'" in mod
    assert 'SELECT id,lifecycle_status FROM r1_restaurant_order_lines' in rel and "state.lifecycle_status!='active'" in rel
    assert "lifecycle_status='active'" not in hist
