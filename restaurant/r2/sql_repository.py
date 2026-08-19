from __future__ import annotations
import json
from decimal import Decimal
from uuid import UUID,uuid4
from sqlalchemy import text
from .contracts import *
from .service import R2Error

class SQLR2Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,t,key,fp,kind):
        row=self.db_session.execute(text('SELECT * FROM r2_restaurant_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE'),{'t':t,'k':key}).first()
        if row:
            if row.request_fingerprint!=fp or row.command_type!=kind:raise R2Error('R2_COMMAND_CONFLICT','idempotency_conflict','Command key already used with different content')
            return row
        return self.db_session.execute(text('INSERT INTO r2_restaurant_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *'),{'t':t,'k':key,'f':fp,'y':kind}).one()
    def _done(self,t,key,typ,p):self.db_session.execute(text('UPDATE r2_restaurant_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k'),{'y':typ,'p':str(p) if p else None,'t':t,'k':key})
    def _id(self,table,t,p):return self.db_session.execute(text(f'SELECT id FROM {table} WHERE tenant_id=:t AND public_id=:p'),{'t':t,'p':str(p)}).scalar()
    def _global_id(self,table,p):return self.db_session.execute(text(f'SELECT id FROM {table} WHERE public_id=:p'),{'p':str(p)}).scalar()
    def _public(self,table,t,i):
        if i is None:return None
        return self.db_session.execute(text(f'SELECT public_id FROM {table} WHERE tenant_id=:t AND id=:i'),{'t':t,'i':i}).scalar()
    def _catalog_id(self,t,p):return self._id('so1_catalogs',t,p)
    def _catalog_public(self,t,i):return self._public('so1_catalogs',t,i)
    def _resource_id(self,t,p):return self._id('so5_resources',t,p)
    def _resource_public(self,t,i):return self._public('so5_resources',t,i)
    def _atomic_id(self,t,p):return self._id('atomic_units',t,p)
    def _atomic_public(self,t,i):return self._public('atomic_units',t,i)
    def _offer_id(self,t,p):return self._id('so1_offers',t,p)
    def _offer_public(self,t,i):return self._public('so1_offers',t,i)
    def _price_id(self,t,p):return self._id('so1_prices',t,p)
    def _price_public(self,t,i):return self._public('so1_prices',t,i)
    def _party_id(self,t,p):return self._id('parties',t,p) if p else None

    def _section(self,r):
        if not r:return None
        return MenuSection(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.catalog_public_id)),r.section_code,r.display_name,r.sort_order,r.effective_from,r.effective_to,r.active,r.metadata,r.row_version)
    def define_section(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'define_menu_section')
        if replay.result_public_id:
            r=self.db_session.execute(text('''SELECT s.*,cat.public_id catalog_public_id FROM r2_restaurant_menu_sections s JOIN so1_catalogs cat ON (cat.tenant_id,cat.id)=(s.tenant_id,s.catalog_id) WHERE s.tenant_id=:t AND s.public_id=:p'''),{'t':c.tenant_id,'p':str(replay.result_public_id)}).first();return self._section(r)
        cid=self._catalog_id(c.tenant_id,c.catalog_public_id)
        if cid is None:return None
        self.db_session.execute(text('''INSERT INTO r2_restaurant_menu_sections(public_id,tenant_id,catalog_id,section_code,display_name,sort_order,effective_from,effective_to,metadata) VALUES(:p,:t,:c,:code,:n,:s,:f,:to,CAST(:m AS jsonb))'''),{'p':str(p),'t':c.tenant_id,'c':cid,'code':c.section_code,'n':c.display_name,'s':c.sort_order,'f':c.effective_from,'to':c.effective_to,'m':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'menu_section',p)
        r=self.db_session.execute(text('''SELECT s.*,cat.public_id catalog_public_id FROM r2_restaurant_menu_sections s JOIN so1_catalogs cat ON (cat.tenant_id,cat.id)=(s.tenant_id,s.catalog_id) WHERE s.tenant_id=:t AND s.public_id=:p'''),{'t':c.tenant_id,'p':str(p)}).first();return self._section(r)
    def section(self,t,p):
        r=self.db_session.execute(text('''SELECT s.*,cat.public_id catalog_public_id FROM r2_restaurant_menu_sections s JOIN so1_catalogs cat ON (cat.tenant_id,cat.id)=(s.tenant_id,s.catalog_id) WHERE s.tenant_id=:t AND s.public_id=:p'''),{'t':t,'p':str(p)}).first();return self._section(r)
    def place_menu_entry(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'place_menu_entry')
        if not replay.completed_at:
            row=self.db_session.execute(text('''INSERT INTO r2_restaurant_menu_section_entries(tenant_id,section_id,catalog_entry_public_id,sort_order,effective_from,effective_to) SELECT s.tenant_id,s.id,e.public_id,:sort,:f,:to FROM r2_restaurant_menu_sections s JOIN so1_catalog_entries e ON e.tenant_id=s.tenant_id AND e.catalog_id=s.catalog_id WHERE s.tenant_id=:t AND s.public_id=:section AND e.public_id=:entry ON CONFLICT DO NOTHING RETURNING id'''),{'sort':c.sort_order,'f':c.effective_from,'to':c.effective_to,'t':c.tenant_id,'section':str(c.section_public_id),'entry':str(c.catalog_entry_public_id)}).scalar()
            if row is None:return None
            self._done(c.tenant_id,c.command_key,'menu_section_entry',None)
        r=self.db_session.execute(text('''SELECT e.tenant_id,s.public_id section_public_id,e.catalog_entry_public_id,e.sort_order,e.effective_from,e.effective_to FROM r2_restaurant_menu_section_entries e JOIN r2_restaurant_menu_sections s ON (s.tenant_id,s.id)=(e.tenant_id,e.section_id) WHERE e.tenant_id=:t AND s.public_id=:section AND e.catalog_entry_public_id=:entry AND e.effective_from=:f'''),{'t':c.tenant_id,'section':str(c.section_public_id),'entry':str(c.catalog_entry_public_id),'f':c.effective_from}).first()
        return MenuSectionEntry(r.tenant_id,UUID(str(r.section_public_id)),UUID(str(r.catalog_entry_public_id)),r.sort_order,r.effective_from,r.effective_to) if r else None
    def bind_menu_entry_modifier_group(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'bind_menu_entry_modifier_group')
        if not replay.completed_at:
            row=self.db_session.execute(text('''INSERT INTO r2_restaurant_menu_entry_modifier_groups(tenant_id,catalog_entry_public_id,modifier_group_id,sequence,effective_from,effective_to) SELECT g.tenant_id,e.public_id,g.id,:seq,:f,:to FROM r2_restaurant_modifier_groups g JOIN so1_catalog_entries e ON e.tenant_id=g.tenant_id WHERE g.tenant_id=:t AND g.public_id=:group AND e.public_id=:entry ON CONFLICT DO NOTHING RETURNING id'''),{'seq':c.sequence,'f':c.effective_from,'to':c.effective_to,'t':c.tenant_id,'group':str(c.modifier_group_public_id),'entry':str(c.catalog_entry_public_id)}).scalar()
            if row is None:return None
            self._done(c.tenant_id,c.command_key,'menu_entry_modifier_group',None)
        r=self.db_session.execute(text('''SELECT m.tenant_id,m.catalog_entry_public_id,g.public_id group_public_id,m.sequence,m.effective_from,m.effective_to FROM r2_restaurant_menu_entry_modifier_groups m JOIN r2_restaurant_modifier_groups g ON (g.tenant_id,g.id)=(m.tenant_id,m.modifier_group_id) WHERE m.tenant_id=:t AND m.catalog_entry_public_id=:entry AND g.public_id=:group AND m.effective_from=:f'''),{'t':c.tenant_id,'entry':str(c.catalog_entry_public_id),'group':str(c.modifier_group_public_id),'f':c.effective_from}).first()
        return MenuEntryModifierBinding(r.tenant_id,UUID(str(r.catalog_entry_public_id)),UUID(str(r.group_public_id)),r.sequence,r.effective_from,r.effective_to) if r else None

    def _group(self,r):
        if not r:return None
        return ModifierGroup(UUID(str(r.public_id)),r.tenant_id,r.group_code,r.display_name,SelectionMode(r.selection_mode),r.minimum_selections,r.maximum_selections,r.effective_from,r.effective_to,r.active,r.metadata,r.row_version)
    def define_modifier_group(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'define_modifier_group')
        if replay.result_public_id:return self.modifier_group(c.tenant_id,UUID(str(replay.result_public_id)))
        self.db_session.execute(text('''INSERT INTO r2_restaurant_modifier_groups(public_id,tenant_id,group_code,display_name,selection_mode,minimum_selections,maximum_selections,effective_from,effective_to,metadata) VALUES(:p,:t,:c,:n,:m,:min,:max,:f,:to,CAST(:meta AS jsonb))'''),{'p':str(p),'t':c.tenant_id,'c':c.group_code,'n':c.display_name,'m':c.selection_mode.value,'min':c.minimum_selections,'max':c.maximum_selections,'f':c.effective_from,'to':c.effective_to,'meta':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'modifier_group',p);return self.modifier_group(c.tenant_id,p)
    def modifier_group(self,t,p):return self._group(self.db_session.execute(text('SELECT * FROM r2_restaurant_modifier_groups WHERE tenant_id=:t AND public_id=:p'),{'t':t,'p':str(p)}).first())
    def _option(self,r):
        if not r:return None
        target=None;typ=TargetType(r.target_type) if r.target_type else None
        if typ is TargetType.ATOMIC_UNIT:target=UUID(str(r.atomic_public_id))
        elif typ is TargetType.OFFER:target=UUID(str(r.offer_public_id))
        return ModifierOption(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.group_public_id)),r.option_code,r.display_name,ModifierEffect(r.effect_type),typ,target,UUID(str(r.price_public_id)) if r.price_public_id else None,Decimal(r.default_quantity),r.preparation_instruction,r.active,r.sort_order,r.metadata)
    def add_modifier_option(self,c,p,price_amount,currency,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'add_modifier_option')
        if replay.result_public_id:return self.modifier_option(c.tenant_id,UUID(str(replay.result_public_id)))
        gid=self._id('r2_restaurant_modifier_groups',c.tenant_id,c.group_public_id);aid=self._atomic_id(c.tenant_id,c.target_public_id) if c.target_type is TargetType.ATOMIC_UNIT else None;oid=self._offer_id(c.tenant_id,c.target_public_id) if c.target_type is TargetType.OFFER else None;pid=self._price_id(c.tenant_id,c.price_public_id) if c.price_public_id else None
        if gid is None or (c.target_public_id and aid is None and oid is None) or (c.price_public_id and pid is None):return None
        self.db_session.execute(text('''INSERT INTO r2_restaurant_modifier_options(public_id,tenant_id,modifier_group_id,option_code,display_name,effect_type,target_type,atomic_unit_id,offer_id,price_id,default_quantity,preparation_instruction,sort_order,metadata) VALUES(:p,:t,:g,:c,:n,:e,:tt,:a,:o,:price,:q,:i,:s,CAST(:m AS jsonb))'''),{'p':str(p),'t':c.tenant_id,'g':gid,'c':c.option_code,'n':c.display_name,'e':c.effect_type.value,'tt':c.target_type.value if c.target_type else None,'a':aid,'o':oid,'price':pid,'q':c.default_quantity,'i':c.preparation_instruction,'s':c.sort_order,'m':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'modifier_option',p);return self.modifier_option(c.tenant_id,p)
    def modifier_option(self,t,p):
        r=self.db_session.execute(text('''SELECT o.*,g.public_id group_public_id,a.public_id atomic_public_id,off.public_id offer_public_id,price.public_id price_public_id FROM r2_restaurant_modifier_options o JOIN r2_restaurant_modifier_groups g ON (g.tenant_id,g.id)=(o.tenant_id,o.modifier_group_id) LEFT JOIN atomic_units a ON (a.tenant_id,a.id)=(o.tenant_id,o.atomic_unit_id) LEFT JOIN so1_offers off ON (off.tenant_id,off.id)=(o.tenant_id,o.offer_id) LEFT JOIN so1_prices price ON price.id=o.price_id WHERE o.tenant_id=:t AND o.public_id=:p'''),{'t':t,'p':str(p)}).first();return self._option(r)
    def allowed_modifier_groups_for_line(self,t,line_public_id,at):
        row=self.db_session.execute(text('''SELECT l.id,l.target_type,l.atomic_unit_id,l.offer_id FROM r1_restaurant_order_lines l WHERE l.tenant_id=:t AND l.public_id=:p'''),{'t':t,'p':str(line_public_id)}).first()
        if not row:return ()
        entries=self.db_session.execute(text('''SELECT e.public_id FROM so1_catalog_entries e WHERE e.tenant_id=:t AND e.enabled=true AND e.effective_from<=:at AND (e.effective_to IS NULL OR :at<e.effective_to) AND ((:typ='atomic_unit' AND e.atomic_unit_id=:a) OR (:typ='offer' AND e.offer_id=:o))'''),{'t':t,'typ':row.target_type,'a':row.atomic_unit_id,'o':row.offer_id,'at':at}).scalars().all()
        if not entries:return ()
        rows=self.db_session.execute(text('''SELECT DISTINCT g.* FROM r2_restaurant_menu_entry_modifier_groups m JOIN r2_restaurant_modifier_groups g ON (g.tenant_id,g.id)=(m.tenant_id,m.modifier_group_id) WHERE m.tenant_id=:t AND m.catalog_entry_public_id=ANY(:entries) AND m.effective_from<=:at AND (m.effective_to IS NULL OR :at<m.effective_to) AND g.active=true AND g.effective_from<=:at AND (g.effective_to IS NULL OR :at<g.effective_to) ORDER BY g.group_code'''),{'t':t,'entries':list(entries),'at':at}).all();return tuple(self._group(x) for x in rows)
    def set_line_modifiers(self,c,p,normalized,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'set_line_modifiers')
        if replay.result_public_id:return self.modifier_set(c.tenant_id,c.order_line_public_id)
        line=self.db_session.execute(text('''SELECT l.id,o.lifecycle_status FROM r1_restaurant_order_lines l JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(l.tenant_id,l.order_id) WHERE l.tenant_id=:t AND l.public_id=:p FOR UPDATE OF o'''),{'t':c.tenant_id,'p':str(c.order_line_public_id)}).first()
        if not line or line.lifecycle_status!='open':return None
        version=self.db_session.execute(text('SELECT COALESCE(max(selection_version),0)+1 FROM r2_restaurant_order_line_modifier_sets WHERE tenant_id=:t AND order_line_id=:l'),{'t':c.tenant_id,'l':line.id}).scalar_one()
        party=self._party_id(c.tenant_id,c.created_by_party_public_id)
        setrow=self.db_session.execute(text('INSERT INTO r2_restaurant_order_line_modifier_sets(public_id,tenant_id,order_line_id,selection_version,created_at,created_by_party_id) VALUES(:p,:t,:l,:v,:at,:party) RETURNING id'),{'p':str(p),'t':c.tenant_id,'l':line.id,'v':version,'at':c.occurred_at,'party':party}).one()
        for x in normalized:
            g=self._id('r2_restaurant_modifier_groups',c.tenant_id,x.group_public_id);o=self._id('r2_restaurant_modifier_options',c.tenant_id,x.option_public_id);opt=self.modifier_option(c.tenant_id,x.option_public_id);amount=Decimal('0');currency=None
            if opt and opt.price_public_id:
                pr=self.db_session.execute(text('SELECT amount,currency FROM so1_prices WHERE tenant_id=:t AND public_id=:p'),{'t':c.tenant_id,'p':str(opt.price_public_id)}).first();amount=Decimal(pr.amount) if pr else Decimal('0');currency=pr.currency if pr else None
            self.db_session.execute(text('INSERT INTO r2_restaurant_order_line_modifier_items(tenant_id,modifier_set_id,modifier_group_id,modifier_option_id,quantity,price_amount_snapshot,currency,instruction_snapshot) VALUES(:t,:s,:g,:o,:q,:a,:c,:i)'),{'t':c.tenant_id,'s':setrow.id,'g':g,'o':o,'q':x.quantity,'a':amount,'c':currency,'i':opt.preparation_instruction if opt else None})
        self._done(c.tenant_id,c.command_key,'modifier_set',p);return self.modifier_set(c.tenant_id,c.order_line_public_id)
    def modifier_set(self,t,line_public_id):
        r=self.db_session.execute(text('''SELECT s.*,l.public_id line_public_id FROM r2_restaurant_order_line_modifier_sets s JOIN r1_restaurant_order_lines l ON (l.tenant_id,l.id)=(s.tenant_id,s.order_line_id) WHERE s.tenant_id=:t AND l.public_id=:p ORDER BY s.selection_version DESC LIMIT 1'''),{'t':t,'p':str(line_public_id)}).first()
        if not r:return None
        rows=self.db_session.execute(text('''SELECT g.public_id group_public_id,o.public_id option_public_id,i.quantity,i.price_amount_snapshot,i.currency,i.instruction_snapshot FROM r2_restaurant_order_line_modifier_items i JOIN r2_restaurant_modifier_groups g ON (g.tenant_id,g.id)=(i.tenant_id,i.modifier_group_id) JOIN r2_restaurant_modifier_options o ON (o.tenant_id,o.id)=(i.tenant_id,i.modifier_option_id) WHERE i.tenant_id=:t AND i.modifier_set_id=:s ORDER BY i.id'''),{'t':t,'s':r.id}).all();sel=tuple(ModifierSelection(UUID(str(x.group_public_id)),UUID(str(x.option_public_id)),Decimal(x.quantity),Decimal(x.price_amount_snapshot),x.currency,x.instruction_snapshot) for x in rows);return ModifierSelectionSet(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.line_public_id)),r.selection_version,sel,r.created_at)
    def _station(self,r):
        if not r:return None
        return StationProfile(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.resource_public_id)),r.station_code,r.display_name,StationKind(r.station_kind),r.output_channel_code,r.destination_reference,r.active,r.metadata,r.row_version)
    def profile_station(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'profile_station')
        if replay.result_public_id:return self.station(c.tenant_id,c.resource_public_id)
        rid=self._resource_id(c.tenant_id,c.resource_public_id)
        if rid is None:return None
        self.db_session.execute(text('''INSERT INTO r2_restaurant_station_profiles(public_id,tenant_id,resource_id,station_code,display_name,station_kind,output_channel_code,destination_reference,metadata) VALUES(:p,:t,:r,:c,:n,:k,:ch,:d,CAST(:m AS jsonb)) ON CONFLICT(tenant_id,resource_id) DO UPDATE SET station_code=EXCLUDED.station_code,display_name=EXCLUDED.display_name,station_kind=EXCLUDED.station_kind,output_channel_code=EXCLUDED.output_channel_code,destination_reference=EXCLUDED.destination_reference,metadata=EXCLUDED.metadata,updated_at=now(),row_version=r2_restaurant_station_profiles.row_version+1'''),{'p':str(p),'t':c.tenant_id,'r':rid,'c':c.station_code,'n':c.display_name,'k':c.station_kind.value,'ch':c.output_channel_code,'d':c.destination_reference,'m':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'station_profile',p);return self.station(c.tenant_id,c.resource_public_id)
    def station(self,t,resource_public_id):
        r=self.db_session.execute(text('''SELECT s.*,res.public_id resource_public_id FROM r2_restaurant_station_profiles s JOIN so5_resources res ON (res.tenant_id,res.id)=(s.tenant_id,s.resource_id) WHERE s.tenant_id=:t AND res.public_id=:p'''),{'t':t,'p':str(resource_public_id)}).first();return self._station(r)
    def define_route(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'define_route')
        if replay.result_public_id:return self._route_by_public(c.tenant_id,UUID(str(replay.result_public_id)))
        station=self.db_session.execute(text('''SELECT s.id FROM r2_restaurant_station_profiles s JOIN so5_resources r ON (r.tenant_id,r.id)=(s.tenant_id,s.resource_id) WHERE s.tenant_id=:t AND r.public_id=:p'''),{'t':c.tenant_id,'p':str(c.station_resource_public_id)}).scalar();aid=self._atomic_id(c.tenant_id,c.target_public_id) if c.target_type is TargetType.ATOMIC_UNIT else None;oid=self._offer_id(c.tenant_id,c.target_public_id) if c.target_type is TargetType.OFFER else None;mode=self.db_session.execute(text('SELECT id FROM r1_restaurant_service_modes WHERE tenant_id=:t AND mode_code=:c'),{'t':c.tenant_id,'c':c.service_mode_code}).scalar() if c.service_mode_code else None
        if station is None:return None
        self.db_session.execute(text('''INSERT INTO r2_restaurant_routing_rules(public_id,tenant_id,rule_code,station_profile_id,target_type,atomic_unit_id,offer_id,semantic_reference,service_mode_id,source_channel_code,course_code,priority,effective_from,effective_to,metadata) VALUES(:p,:t,:c,:s,:tt,:a,:o,:sem,:m,:src,:course,:pri,:f,:to,CAST(:meta AS jsonb))'''),{'p':str(p),'t':c.tenant_id,'c':c.rule_code,'s':station,'tt':c.target_type.value if c.target_type else None,'a':aid,'o':oid,'sem':c.semantic_reference,'m':mode,'src':c.source_channel_code,'course':c.course_code,'pri':c.priority,'f':c.effective_from,'to':c.effective_to,'meta':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'routing_rule',p);return self._route_by_public(c.tenant_id,p)
    def _route(self,r):
        if not r:return None
        typ=TargetType(r.target_type) if r.target_type else None;target=UUID(str(r.atomic_public_id)) if typ is TargetType.ATOMIC_UNIT else UUID(str(r.offer_public_id)) if typ is TargetType.OFFER else None
        return RoutingRule(UUID(str(r.public_id)),r.tenant_id,r.rule_code,UUID(str(r.station_resource_public_id)),typ,target,r.semantic_reference,r.mode_code,r.source_channel_code,r.course_code,r.priority,r.effective_from,r.effective_to,r.active,r.metadata)
    def _route_by_public(self,t,p):
        r=self.db_session.execute(text('''SELECT rr.*,res.public_id station_resource_public_id,a.public_id atomic_public_id,o.public_id offer_public_id,m.mode_code FROM r2_restaurant_routing_rules rr JOIN r2_restaurant_station_profiles s ON (s.tenant_id,s.id)=(rr.tenant_id,rr.station_profile_id) JOIN so5_resources res ON (res.tenant_id,res.id)=(s.tenant_id,s.resource_id) LEFT JOIN atomic_units a ON (a.tenant_id,a.id)=(rr.tenant_id,rr.atomic_unit_id) LEFT JOIN so1_offers o ON (o.tenant_id,o.id)=(rr.tenant_id,rr.offer_id) LEFT JOIN r1_restaurant_service_modes m ON (m.tenant_id,m.id)=(rr.tenant_id,rr.service_mode_id) WHERE rr.tenant_id=:t AND rr.public_id=:p'''),{'t':t,'p':str(p)}).first();return self._route(r)
    def routes_for_line(self,t,line,order,at):
        aid=self._atomic_id(t,line.target_public_id) if getattr(getattr(line,'target_type',None),'value',getattr(line,'target_type',None))=='atomic_unit' else None;oid=self._offer_id(t,line.target_public_id) if getattr(getattr(line,'target_type',None),'value',getattr(line,'target_type',None))=='offer' else None
        rows=self.db_session.execute(text('''SELECT rr.public_id FROM r2_restaurant_routing_rules rr LEFT JOIN r1_restaurant_service_modes m ON (m.tenant_id,m.id)=(rr.tenant_id,rr.service_mode_id) WHERE rr.tenant_id=:t AND rr.active=true AND rr.effective_from<=:at AND (rr.effective_to IS NULL OR :at<rr.effective_to) AND (((rr.target_type='atomic_unit' AND rr.atomic_unit_id=:a) OR (rr.target_type='offer' AND rr.offer_id=:o)) OR rr.semantic_reference IS NOT NULL) AND (rr.service_mode_id IS NULL OR m.mode_code=:mode) AND (rr.source_channel_code IS NULL OR rr.source_channel_code=:src) ORDER BY rr.priority,rr.id'''),{'t':t,'at':at,'a':aid,'o':oid,'mode':getattr(order,'mode_code',None),'src':getattr(order,'source_channel_code',None)}).scalars().all();return tuple(self._route_by_public(t,UUID(str(x))) for x in rows)
    def define_preparation_spec(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'define_preparation_spec')
        if replay.result_public_id:return self.preparation_spec(c.tenant_id,UUID(str(replay.result_public_id)))
        output=self._atomic_id(c.tenant_id,c.output_atomic_unit_public_id)
        if output is None:return None
        row=self.db_session.execute(text('''INSERT INTO r2_restaurant_preparation_specs(public_id,tenant_id,spec_code,spec_version,display_name,output_atomic_unit_id,yield_stock_units,effective_from,effective_to,metadata) VALUES(:p,:t,:c,:v,:n,:o,:y,:f,:to,CAST(:m AS jsonb)) RETURNING id'''),{'p':str(p),'t':c.tenant_id,'c':c.spec_code,'v':c.spec_version,'n':c.display_name,'o':output,'y':c.yield_stock_units,'f':c.effective_from,'to':c.effective_to,'m':json.dumps(c.metadata,sort_keys=True)}).one()
        for x in c.components:
            aid=self._atomic_id(c.tenant_id,x.atomic_unit_public_id) if x.atomic_unit_public_id else None;dep=self._id('r2_restaurant_preparation_specs',c.tenant_id,x.dependency_spec_public_id) if x.dependency_spec_public_id else None
            self.db_session.execute(text('''INSERT INTO r2_restaurant_preparation_components(tenant_id,preparation_spec_id,component_type,atomic_unit_id,dependency_spec_id,required_stock_units,sequence,optional,metadata) VALUES(:t,:s,:typ,:a,:d,:q,:seq,:opt,CAST(:m AS jsonb))'''),{'t':c.tenant_id,'s':row.id,'typ':x.component_type,'a':aid,'d':dep,'q':x.required_stock_units,'seq':x.sequence,'opt':x.optional,'m':json.dumps(x.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'preparation_spec',p);return self.preparation_spec(c.tenant_id,p)
    def preparation_spec(self,t,p):
        r=self.db_session.execute(text('''SELECT s.*,a.public_id output_public_id FROM r2_restaurant_preparation_specs s JOIN atomic_units a ON (a.tenant_id,a.id)=(s.tenant_id,s.output_atomic_unit_id) WHERE s.tenant_id=:t AND s.public_id=:p'''),{'t':t,'p':str(p)}).first()
        if not r:return None
        rows=self.db_session.execute(text('''SELECT c.*,a.public_id atomic_public_id,d.public_id dependency_public_id FROM r2_restaurant_preparation_components c LEFT JOIN atomic_units a ON (a.tenant_id,a.id)=(c.tenant_id,c.atomic_unit_id) LEFT JOIN r2_restaurant_preparation_specs d ON (d.tenant_id,d.id)=(c.tenant_id,c.dependency_spec_id) WHERE c.tenant_id=:t AND c.preparation_spec_id=:s ORDER BY c.sequence,c.id'''),{'t':t,'s':r.id}).all();components=tuple(PreparationComponent(x.component_type,UUID(str(x.atomic_public_id)) if x.atomic_public_id else None,UUID(str(x.dependency_public_id)) if x.dependency_public_id else None,x.required_stock_units,x.sequence,x.optional,x.metadata) for x in rows);return PreparationSpec(UUID(str(r.public_id)),r.tenant_id,r.spec_code,r.spec_version,r.display_name,UUID(str(r.output_public_id)),r.yield_stock_units,r.effective_from,r.effective_to,components,r.lifecycle_status,r.metadata)
    def release_preparation(self,c,plans,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'release_preparation')
        if replay.completed_at:
            rows=self.db_session.execute(text('''SELECT public_id FROM r2_restaurant_preparation_tickets WHERE tenant_id=:t AND release_command_key=:k ORDER BY id'''),{'t':c.tenant_id,'k':c.command_key}).scalars().all();return tuple(self.ticket(c.tenant_id,UUID(str(x))) for x in rows)
        order=self.db_session.execute(text('SELECT id,lifecycle_status FROM r1_restaurant_orders WHERE tenant_id=:t AND public_id=:p FOR UPDATE'),{'t':c.tenant_id,'p':str(c.order_public_id)}).first()
        if not order or order.lifecycle_status!='submitted':return None
        grouped={}
        for plan in plans:
            route=plan['route'];key=(route.station_resource_public_id,route.course_code or c.course_code);grouped.setdefault(key,[]).append(plan)
        tickets=[]
        for idx,((station_resource,course),items) in enumerate(sorted(grouped.items(),key=lambda x:(str(x[0][0]),x[0][1] or '')),1):
            station=self.db_session.execute(text('''SELECT s.id FROM r2_restaurant_station_profiles s JOIN so5_resources r ON (r.tenant_id,r.id)=(s.tenant_id,s.resource_id) WHERE s.tenant_id=:t AND r.public_id=:p'''),{'t':c.tenant_id,'p':str(station_resource)}).scalar()
            line_ids=[self._id('r1_restaurant_order_lines',c.tenant_id,x['line'].public_id) for x in items]
            duplicate=self.db_session.execute(text('''SELECT 1 FROM r2_restaurant_preparation_ticket_items i JOIN r2_restaurant_preparation_tickets t ON (t.tenant_id,t.id)=(i.tenant_id,i.ticket_id) WHERE i.tenant_id=:tnt AND i.order_line_id=ANY(:lines) AND t.station_profile_id=:station AND COALESCE(t.course_code,'')=COALESCE(:course,'') AND t.lifecycle_status<>'voided' LIMIT 1'''),{'tnt':c.tenant_id,'lines':line_ids,'station':station,'course':course}).scalar()
            if duplicate:return None
            ticket_public=uuid4();code=f'{str(c.order_public_id)[:8]}-{str(ticket_public)[:8]}';status='held' if c.hold else 'queued'
            tr=self.db_session.execute(text('''INSERT INTO r2_restaurant_preparation_tickets(public_id,tenant_id,order_id,station_profile_id,release_command_key,ticket_code,lifecycle_status,course_code,priority,held,released_at) VALUES(:p,:t,:o,:s,:k,:c,:st,:course,:pri,:held,:at) RETURNING id'''),{'p':str(ticket_public),'t':c.tenant_id,'o':order.id,'s':station,'k':c.command_key,'c':code,'st':status,'course':course,'pri':min(x['route'].priority for x in items),'held':c.hold,'at':c.occurred_at}).one();self.db_session.execute(text('INSERT INTO r2_restaurant_ticket_history(tenant_id,ticket_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:id,:e,:st,:r,:at,\'{}\'::jsonb)'),{'t':c.tenant_id,'id':tr.id,'e':'held' if c.hold else 'released','st':status,'r':'release_preparation','at':c.occurred_at})
            for n,plan in enumerate(items,1):
                line=plan['line'];lineid=self._id('r1_restaurant_order_lines',c.tenant_id,line.public_id);modset=plan.get('modifier_set');msid=self._id('r2_restaurant_order_line_modifier_sets',c.tenant_id,modset.public_id) if modset else None;snapshot=[]
                if modset:
                    for sel in modset.selections:snapshot.append({'group_public_id':str(sel.group_public_id),'option_public_id':str(sel.option_public_id),'quantity':str(sel.quantity),'price_amount_snapshot':str(sel.price_amount_snapshot),'currency':sel.currency,'instruction_snapshot':sel.instruction_snapshot})
                item_public=uuid4();self.db_session.execute(text('''INSERT INTO r2_restaurant_preparation_ticket_items(public_id,tenant_id,ticket_id,order_line_id,modifier_set_id,quantity,lifecycle_status,preparation_note,modifier_snapshot) VALUES(:p,:t,:ticket,:line,:m,:q,:st,:note,CAST(:snap AS jsonb))'''),{'p':str(item_public),'t':c.tenant_id,'ticket':tr.id,'line':lineid,'m':msid,'q':line.quantity,'st':status,'note':getattr(line,'note',None),'snap':json.dumps(snapshot,sort_keys=True)})
            tickets.append(ticket_public)
        self._done(c.tenant_id,c.command_key,'preparation_release',None);return tuple(self.ticket(c.tenant_id,p) for p in tickets)
    def ticket(self,t,p):
        r=self.db_session.execute(text('''SELECT x.*,o.public_id order_public_id,res.public_id station_resource_public_id FROM r2_restaurant_preparation_tickets x JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(x.tenant_id,x.order_id) JOIN r2_restaurant_station_profiles s ON (s.tenant_id,s.id)=(x.tenant_id,x.station_profile_id) JOIN so5_resources res ON (res.tenant_id,res.id)=(s.tenant_id,s.resource_id) WHERE x.tenant_id=:t AND x.public_id=:p'''),{'t':t,'p':str(p)}).first()
        if not r:return None
        rows=self.db_session.execute(text('''SELECT i.*,l.public_id line_public_id,ms.public_id modifier_set_public_id FROM r2_restaurant_preparation_ticket_items i JOIN r1_restaurant_order_lines l ON (l.tenant_id,l.id)=(i.tenant_id,i.order_line_id) LEFT JOIN r2_restaurant_order_line_modifier_sets ms ON (ms.tenant_id,ms.id)=(i.tenant_id,i.modifier_set_id) WHERE i.tenant_id=:t AND i.ticket_id=:id ORDER BY i.id'''),{'t':t,'id':r.id}).all();items=tuple(PreparationTicketItem(UUID(str(x.public_id)),x.tenant_id,UUID(str(r.public_id)),UUID(str(x.line_public_id)),Decimal(x.quantity),TicketItemStatus(x.lifecycle_status),UUID(str(x.modifier_set_public_id)) if x.modifier_set_public_id else None,x.preparation_note,tuple(x.modifier_snapshot or ()),x.row_version) for x in rows);return PreparationTicket(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.order_public_id)),UUID(str(r.station_resource_public_id)),r.ticket_code,TicketStatus(r.lifecycle_status),r.course_code,r.priority,r.held,r.released_at,r.fired_at,r.completed_at,items,r.row_version)
    def ticket_item(self,t,p):
        r=self.db_session.execute(text('''SELECT i.*,t.public_id ticket_public_id,l.public_id line_public_id,ms.public_id modifier_set_public_id FROM r2_restaurant_preparation_ticket_items i JOIN r2_restaurant_preparation_tickets t ON (t.tenant_id,t.id)=(i.tenant_id,i.ticket_id) JOIN r1_restaurant_order_lines l ON (l.tenant_id,l.id)=(i.tenant_id,i.order_line_id) LEFT JOIN r2_restaurant_order_line_modifier_sets ms ON (ms.tenant_id,ms.id)=(i.tenant_id,i.modifier_set_id) WHERE i.tenant_id=:t AND i.public_id=:p'''),{'t':t,'p':str(p)}).first()
        if not r:return None
        return PreparationTicketItem(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.ticket_public_id)),UUID(str(r.line_public_id)),Decimal(r.quantity),TicketItemStatus(r.lifecycle_status),UUID(str(r.modifier_set_public_id)) if r.modifier_set_public_id else None,r.preparation_note,tuple(r.modifier_snapshot or ()),r.row_version)
    def fire_ticket(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'fire_ticket')
        if replay.result_public_id:return self.ticket(c.tenant_id,UUID(str(replay.result_public_id)))
        r=self.db_session.execute(text('SELECT id,lifecycle_status,row_version FROM r2_restaurant_preparation_tickets WHERE tenant_id=:t AND public_id=:p FOR UPDATE'),{'t':c.tenant_id,'p':str(c.ticket_public_id)}).first()
        if not r or r.row_version!=c.expected_version or r.lifecycle_status!='held':return None
        self.db_session.execute(text("UPDATE r2_restaurant_preparation_tickets SET lifecycle_status='queued',held=false,fired_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{'at':c.occurred_at,'t':c.tenant_id,'id':r.id});self.db_session.execute(text("UPDATE r2_restaurant_preparation_ticket_items SET lifecycle_status='queued',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND ticket_id=:id AND lifecycle_status='held'"),{'t':c.tenant_id,'id':r.id});self._done(c.tenant_id,c.command_key,'preparation_ticket',c.ticket_public_id);return self.ticket(c.tenant_id,c.ticket_public_id)
    def advance_ticket_item(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'advance_ticket_item')
        if replay.result_public_id:return self.ticket_item(c.tenant_id,UUID(str(replay.result_public_id)))
        r=self.db_session.execute(text('SELECT id,ticket_id,lifecycle_status,row_version FROM r2_restaurant_preparation_ticket_items WHERE tenant_id=:t AND public_id=:p FOR UPDATE'),{'t':c.tenant_id,'p':str(c.ticket_item_public_id)}).first()
        allowed={('queued','in_progress'),('in_progress','ready'),('ready','completed'),('held','voided'),('queued','voided'),('in_progress','voided')}
        if not r or r.row_version!=c.expected_version or (r.lifecycle_status,c.to_status.value) not in allowed:return None
        self.db_session.execute(text('UPDATE r2_restaurant_preparation_ticket_items SET lifecycle_status=:st,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id'),{'st':c.to_status.value,'t':c.tenant_id,'id':r.id})
        self.db_session.execute(text('INSERT INTO r2_restaurant_ticket_item_history(tenant_id,ticket_item_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:id,:e,:f,:to,:r,:at,\'{}\'::jsonb)'),{'t':c.tenant_id,'id':r.id,'e':'item_'+c.to_status.value,'f':r.lifecycle_status,'to':c.to_status.value,'r':c.reason_code,'at':c.occurred_at})
        parent=self.db_session.execute(text('SELECT lifecycle_status FROM r2_restaurant_preparation_tickets WHERE tenant_id=:t AND id=:id FOR UPDATE'),{'t':c.tenant_id,'id':r.ticket_id}).first()
        counts=self.db_session.execute(text("""SELECT count(*) FILTER (WHERE lifecycle_status<>'voided') AS active_count,count(*) FILTER (WHERE lifecycle_status IN('ready','completed')) AS ready_count,count(*) FILTER (WHERE lifecycle_status='in_progress') AS in_progress_count FROM r2_restaurant_preparation_ticket_items WHERE tenant_id=:t AND ticket_id=:id"""),{'t':c.tenant_id,'id':r.ticket_id}).one()
        new_status=None
        if parent and parent.lifecycle_status not in {'completed','voided','held'}:
            if counts.active_count>0 and counts.ready_count==counts.active_count:new_status='ready'
            elif counts.ready_count>0:new_status='partially_ready'
            elif counts.in_progress_count>0:new_status='in_progress'
            elif parent.lifecycle_status in {'in_progress','partially_ready','ready'}:new_status='queued'
        if new_status and new_status!=parent.lifecycle_status:
            self.db_session.execute(text('UPDATE r2_restaurant_preparation_tickets SET lifecycle_status=:st,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id'),{'st':new_status,'t':c.tenant_id,'id':r.ticket_id})
            self.db_session.execute(text('INSERT INTO r2_restaurant_ticket_history(tenant_id,ticket_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:id,\'item_rollup\',:f,:to,:r,:at,\'{}\'::jsonb)'),{'t':c.tenant_id,'id':r.ticket_id,'f':parent.lifecycle_status,'to':new_status,'r':c.reason_code,'at':c.occurred_at})
        self._done(c.tenant_id,c.command_key,'preparation_ticket_item',c.ticket_item_public_id);return self.ticket_item(c.tenant_id,c.ticket_item_public_id)
    def complete_ticket(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'complete_ticket')
        if replay.result_public_id:return self.ticket(c.tenant_id,UUID(str(replay.result_public_id)))
        r=self.db_session.execute(text('SELECT id,lifecycle_status,row_version FROM r2_restaurant_preparation_tickets WHERE tenant_id=:t AND public_id=:p FOR UPDATE'),{'t':c.tenant_id,'p':str(c.ticket_public_id)}).first()
        if not r or r.row_version!=c.expected_version or r.lifecycle_status in {'completed','voided','held'}:return None
        remaining=self.db_session.execute(text("SELECT count(*) FROM r2_restaurant_preparation_ticket_items WHERE tenant_id=:t AND ticket_id=:id AND lifecycle_status NOT IN('completed','voided')"),{'t':c.tenant_id,'id':r.id}).scalar_one()
        if remaining:return None
        self.db_session.execute(text("UPDATE r2_restaurant_preparation_tickets SET lifecycle_status='completed',completed_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{'at':c.occurred_at,'t':c.tenant_id,'id':r.id});self._done(c.tenant_id,c.command_key,'preparation_ticket',c.ticket_public_id);return self.ticket(c.tenant_id,c.ticket_public_id)
    def start_preparation_run(self,c,p,inputs,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'start_preparation_run')
        if replay.result_public_id:return self.preparation_run(c.tenant_id,UUID(str(replay.result_public_id)))
        spec=self._id('r2_restaurant_preparation_specs',c.tenant_id,c.preparation_spec_public_id);item=self._id('r2_restaurant_preparation_ticket_items',c.tenant_id,c.ticket_item_public_id) if c.ticket_item_public_id else None
        if spec is None:return None
        row=self.db_session.execute(text("INSERT INTO r2_restaurant_preparation_runs(public_id,tenant_id,preparation_spec_id,ticket_item_id,lifecycle_status,planned_output_units,started_at) VALUES(:p,:t,:s,:i,'in_progress',:q,:at) RETURNING id"),{'p':str(p),'t':c.tenant_id,'s':spec,'i':item,'q':c.planned_output_units,'at':c.started_at}).one()
        for x in inputs:self.db_session.execute(text('INSERT INTO r2_restaurant_preparation_run_inputs(tenant_id,preparation_run_id,atomic_unit_id,planned_stock_units) VALUES(:t,:r,:a,:q)'),{'t':c.tenant_id,'r':row.id,'a':self._atomic_id(c.tenant_id,x.atomic_unit_public_id),'q':x.planned_stock_units})
        self._done(c.tenant_id,c.command_key,'preparation_run',p);return self.preparation_run(c.tenant_id,p)
    def preparation_run(self,t,p):
        r=self.db_session.execute(text('''SELECT x.*,s.public_id spec_public_id,i.public_id ticket_item_public_id FROM r2_restaurant_preparation_runs x JOIN r2_restaurant_preparation_specs s ON (s.tenant_id,s.id)=(x.tenant_id,x.preparation_spec_id) LEFT JOIN r2_restaurant_preparation_ticket_items i ON (i.tenant_id,i.id)=(x.tenant_id,x.ticket_item_id) WHERE x.tenant_id=:t AND x.public_id=:p'''),{'t':t,'p':str(p)}).first()
        if not r:return None
        rows=self.db_session.execute(text('''SELECT i.*,a.public_id atomic_public_id FROM r2_restaurant_preparation_run_inputs i JOIN atomic_units a ON (a.tenant_id,a.id)=(i.tenant_id,i.atomic_unit_id) WHERE i.tenant_id=:t AND i.preparation_run_id=:r ORDER BY i.id'''),{'t':t,'r':r.id}).all();inputs=tuple(PreparationRunInput(UUID(str(x.atomic_public_id)),x.planned_stock_units,x.consumed_stock_units,x.waste_stock_units) for x in rows);return PreparationRun(UUID(str(r.public_id)),r.tenant_id,UUID(str(r.spec_public_id)),UUID(str(r.ticket_item_public_id)) if r.ticket_item_public_id else None,PrepRunStatus(r.lifecycle_status),r.planned_output_units,r.actual_output_units,r.waste_output_units,r.started_at,r.completed_at,inputs,r.row_version)
    def complete_preparation_run(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'complete_preparation_run')
        if replay.result_public_id:return self.preparation_run(c.tenant_id,UUID(str(replay.result_public_id)))
        r=self.db_session.execute(text('SELECT id,lifecycle_status,row_version FROM r2_restaurant_preparation_runs WHERE tenant_id=:t AND public_id=:p FOR UPDATE'),{'t':c.tenant_id,'p':str(c.preparation_run_public_id)}).first()
        if not r or r.lifecycle_status!='in_progress' or r.row_version!=c.expected_version:return None
        for x in c.inputs:self.db_session.execute(text('''UPDATE r2_restaurant_preparation_run_inputs i SET consumed_stock_units=:c,waste_stock_units=:w FROM atomic_units a WHERE i.tenant_id=:t AND i.preparation_run_id=:r AND a.tenant_id=i.tenant_id AND a.id=i.atomic_unit_id AND a.public_id=:p'''),{'c':x.consumed_stock_units,'w':x.waste_stock_units,'t':c.tenant_id,'r':r.id,'p':str(x.atomic_unit_public_id)})
        self.db_session.execute(text("UPDATE r2_restaurant_preparation_runs SET lifecycle_status='completed',actual_output_units=:a,waste_output_units=:w,completed_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{'a':c.actual_output_units,'w':c.waste_output_units,'at':c.occurred_at,'t':c.tenant_id,'id':r.id});self.db_session.execute(text("INSERT INTO r2_restaurant_preparation_run_history(tenant_id,preparation_run_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:id,'completed','in_progress','completed',:r,:at,'{}'::jsonb)"),{'t':c.tenant_id,'id':r.id,'r':c.reason_code,'at':c.occurred_at});self._done(c.tenant_id,c.command_key,'preparation_run',c.preparation_run_public_id);return self.preparation_run(c.tenant_id,c.preparation_run_public_id)
