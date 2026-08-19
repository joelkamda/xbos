from __future__ import annotations
import json
from decimal import Decimal
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import R1Error

class SQLR1Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,t,key,fp,kind):
        row=self.db_session.execute(text('SELECT * FROM r1_restaurant_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE'),{'t':t,'k':key}).first()
        if row:
            if row.request_fingerprint!=fp or row.command_type!=kind:raise R1Error('R1_COMMAND_CONFLICT','idempotency_conflict','Command key already used with different content')
            return row
        return self.db_session.execute(text('INSERT INTO r1_restaurant_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *'),{'t':t,'k':key,'f':fp,'y':kind}).one()
    def _done(self,t,key,typ,p):self.db_session.execute(text('UPDATE r1_restaurant_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k'),{'y':typ,'p':str(p) if p else None,'t':t,'k':key})
    def _mode_row(self,t,code=None,p=None,lock=False):
        suffix=' FOR UPDATE OF m' if lock else ''
        if code is not None:return self.db_session.execute(text('SELECT m.* FROM r1_restaurant_service_modes m WHERE m.tenant_id=:t AND m.mode_code=:v'+suffix),{'t':t,'v':code}).first()
        return self.db_session.execute(text('SELECT m.* FROM r1_restaurant_service_modes m WHERE m.tenant_id=:t AND m.public_id=:v'+suffix),{'t':t,'v':str(p)}).first()
    @staticmethod
    def _mode(r):
        if not r:return None
        return ServiceMode(UUID(str(r.public_id)),r.tenant_id,r.mode_code,r.display_name,r.requires_session,r.requires_resource,r.supports_tabs,r.supports_reservations,r.allows_remote_origin,r.active,r.metadata,r.row_version)
    def define_mode(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'define_mode')
        if replay.result_public_id:return self._mode(self._mode_row(c.tenant_id,p=replay.result_public_id))
        if self._mode_row(c.tenant_id,code=c.mode_code,lock=True):return None
        self.db_session.execute(text('''INSERT INTO r1_restaurant_service_modes(public_id,tenant_id,mode_code,display_name,requires_session,requires_resource,supports_tabs,supports_reservations,allows_remote_origin,metadata) VALUES(:p,:t,:c,:n,:s,:r,:tabs,:res,:remote,CAST(:m AS jsonb))'''),{'p':str(p),'t':c.tenant_id,'c':c.mode_code,'n':c.display_name,'s':c.requires_session,'r':c.requires_resource,'tabs':c.supports_tabs,'res':c.supports_reservations,'remote':c.allows_remote_origin,'m':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'service_mode',p);return self._mode(self._mode_row(c.tenant_id,p=p))
    def mode(self,t,code):return self._mode(self._mode_row(t,code=code))
    def modes(self,t):return tuple(self.mode(t,x.mode_code) for x in self.db_session.execute(text('SELECT mode_code FROM r1_restaurant_service_modes WHERE tenant_id=:t ORDER BY mode_code'),{'t':t}).all())
    def _resource_id(self,t,p):
        if p is None:return None
        return self.db_session.execute(text('SELECT id FROM so5_resources WHERE tenant_id=:t AND public_id=:p'),{'t':t,'p':str(p)}).scalar()
    def profile_resource(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'profile_resource')
        if replay.completed_at:return self.resource_profile(c.tenant_id,c.resource_public_id)
        r=self._resource_id(c.tenant_id,c.resource_public_id);parent=self._resource_id(c.tenant_id,c.parent_resource_public_id)
        if r is None or (c.parent_resource_public_id and parent is None):return None
        self.db_session.execute(text('''INSERT INTO r1_restaurant_resource_profiles(tenant_id,resource_id,role_code,parent_resource_id,service_mode_codes,metadata) VALUES(:t,:r,:role,:parent,:modes,CAST(:meta AS jsonb)) ON CONFLICT(tenant_id,resource_id) DO UPDATE SET role_code=EXCLUDED.role_code,parent_resource_id=EXCLUDED.parent_resource_id,service_mode_codes=EXCLUDED.service_mode_codes,metadata=EXCLUDED.metadata,updated_at=now()'''),{'t':c.tenant_id,'r':r,'role':c.role.value,'parent':parent,'modes':list(c.service_mode_codes),'meta':json.dumps(c.metadata,sort_keys=True)})
        self._done(c.tenant_id,c.command_key,'resource_profile',c.resource_public_id);return self.resource_profile(c.tenant_id,c.resource_public_id)
    def resource_profile(self,t,p):
        r=self.db_session.execute(text('''SELECT x.*,res.public_id resource_public_id,parent.public_id parent_resource_public_id FROM r1_restaurant_resource_profiles x JOIN so5_resources res ON (res.tenant_id,res.id)=(x.tenant_id,x.resource_id) LEFT JOIN so5_resources parent ON (parent.tenant_id,parent.id)=(x.tenant_id,x.parent_resource_id) WHERE x.tenant_id=:t AND res.public_id=:p'''),{'t':t,'p':str(p)}).first()
        if not r:return None
        return ResourceProfile(r.tenant_id,UUID(str(r.resource_public_id)),ResourceRole(r.role_code),UUID(str(r.parent_resource_public_id)) if r.parent_resource_public_id else None,tuple(r.service_mode_codes or ()),r.metadata)
    def _party_id(self,t,p):
        if p is None:return None
        return self.db_session.execute(text('SELECT id FROM parties WHERE tenant_id=:t AND public_id=:p'),{'t':t,'p':str(p)}).scalar()
    def _identity_id(self,p):
        if p is None:return None
        return self.db_session.execute(text('SELECT id FROM identities WHERE public_id=:p'),{'p':str(p)}).scalar()
    def _staff_insert(self,table,fk,t,subject,items):
        for x in items:self.db_session.execute(text(f'INSERT INTO {table}(tenant_id,{fk},role_code,party_id,identity_id) VALUES(:t,:s,:r,:p,:i)'),{'t':t,'s':subject,'r':x.role_code,'p':self._party_id(t,x.party_public_id),'i':self._identity_id(x.identity_public_id)})
    def _staff_read(self,table,fk,t,subject):
        rows=self.db_session.execute(text(f'''SELECT a.role_code,p.public_id party_public_id,i.public_id identity_public_id FROM {table} a JOIN parties p ON (p.tenant_id,p.id)=(a.tenant_id,a.party_id) LEFT JOIN identities i ON i.id=a.identity_id WHERE a.tenant_id=:t AND a.{fk}=:s ORDER BY a.id'''),{'t':t,'s':subject}).all()
        return tuple(StaffAttribution(x.role_code,UUID(str(x.party_public_id)),UUID(str(x.identity_public_id)) if x.identity_public_id else None) for x in rows)
    def _session_row(self,t,p,lock=False):
        suffix=' FOR UPDATE OF s' if lock else ''
        return self.db_session.execute(text('''SELECT s.*,m.mode_code,party.public_id party_public_id,res.public_id reservation_public_id FROM r1_restaurant_service_sessions s JOIN r1_restaurant_service_modes m ON (m.tenant_id,m.id)=(s.tenant_id,s.service_mode_id) LEFT JOIN parties party ON (party.tenant_id,party.id)=(s.tenant_id,s.party_id) LEFT JOIN so10_reservations res ON (res.tenant_id,res.id)=(s.tenant_id,s.reservation_id) WHERE s.tenant_id=:t AND s.public_id=:p'''+suffix),{'t':t,'p':str(p)}).first()
    def _session(self,r):
        if not r:return None
        resources=tuple(UUID(str(x.public_id)) for x in self.db_session.execute(text('''SELECT res.public_id FROM r1_restaurant_session_resources x JOIN so5_resources res ON (res.tenant_id,res.id)=(x.tenant_id,x.resource_id) WHERE x.tenant_id=:t AND x.session_id=:s ORDER BY x.id'''),{'t':r.tenant_id,'s':r.id}).all())
        return ServiceSession(UUID(str(r.public_id)),r.tenant_id,r.mode_code,r.guest_count,SessionStatus(r.lifecycle_status),r.opened_at,r.closed_at,UUID(str(r.reservation_public_id)) if r.reservation_public_id else None,UUID(str(r.party_public_id)) if r.party_public_id else None,resources,self._staff_read('r1_restaurant_session_staff','session_id',r.tenant_id,r.id),r.row_version)
    def open_session(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'open_session')
        if replay.result_public_id:return self.session(c.tenant_id,replay.result_public_id)
        m=self._mode_row(c.tenant_id,code=c.mode_code,lock=True);party=self._party_id(c.tenant_id,c.party_public_id);reservation=None
        if c.reservation_public_id:reservation=self.db_session.execute(text('SELECT id FROM so10_reservations WHERE tenant_id=:t AND public_id=:p'),{'t':c.tenant_id,'p':str(c.reservation_public_id)}).scalar()
        if not m or (c.party_public_id and party is None) or (c.reservation_public_id and reservation is None):return None
        row=self.db_session.execute(text("INSERT INTO r1_restaurant_service_sessions(public_id,tenant_id,service_mode_id,guest_count,lifecycle_status,opened_at,reservation_id,party_id) VALUES(:p,:t,:m,:g,'open',:at,:r,:party) RETURNING id"),{'p':str(p),'t':c.tenant_id,'m':m.id,'g':c.guest_count,'at':c.opened_at,'r':reservation,'party':party}).one()
        for rp in c.resource_public_ids:self.db_session.execute(text('INSERT INTO r1_restaurant_session_resources(tenant_id,session_id,resource_id,assigned_at) VALUES(:t,:s,:r,:at)'),{'t':c.tenant_id,'s':row.id,'r':self._resource_id(c.tenant_id,rp),'at':c.opened_at})
        self._staff_insert('r1_restaurant_session_staff','session_id',c.tenant_id,row.id,c.staff)
        self.db_session.execute(text("INSERT INTO r1_restaurant_session_history(tenant_id,session_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:s,'opened','open','opened',:at,'{}'::jsonb)"),{'t':c.tenant_id,'s':row.id,'at':c.opened_at});self._done(c.tenant_id,c.command_key,'service_session',p);return self.session(c.tenant_id,p)
    def session(self,t,p):return self._session(self._session_row(t,p))
    def close_session(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'close_session')
        if replay.result_public_id:return self.session(c.tenant_id,replay.result_public_id)
        s=self._session_row(c.tenant_id,c.session_public_id,True)
        if not s or s.row_version!=c.expected_version or s.lifecycle_status!='open' or c.occurred_at<s.opened_at:return None
        if self.db_session.execute(text("SELECT 1 FROM r1_restaurant_orders WHERE tenant_id=:t AND service_session_id=:s AND lifecycle_status='open' LIMIT 1"),{'t':c.tenant_id,'s':s.id}).scalar():return None
        self.db_session.execute(text("UPDATE r1_restaurant_service_sessions SET lifecycle_status='closed',closed_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:s AND row_version=:v"),{'at':c.occurred_at,'t':c.tenant_id,'s':s.id,'v':c.expected_version});self.db_session.execute(text("INSERT INTO r1_restaurant_session_history(tenant_id,session_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:s,'closed','open','closed',:r,:at,'{}'::jsonb)"),{'t':c.tenant_id,'s':s.id,'r':c.reason_code,'at':c.occurred_at});self._done(c.tenant_id,c.command_key,'service_session',c.session_public_id);return self.session(c.tenant_id,c.session_public_id)
    def _order_row(self,t,p,lock=False):
        suffix=' FOR UPDATE OF o' if lock else ''
        return self.db_session.execute(text('''SELECT o.*,m.mode_code,s.public_id session_public_id,p.public_id party_public_id FROM r1_restaurant_orders o JOIN r1_restaurant_service_modes m ON (m.tenant_id,m.id)=(o.tenant_id,o.service_mode_id) LEFT JOIN r1_restaurant_service_sessions s ON (s.tenant_id,s.id)=(o.tenant_id,o.service_session_id) LEFT JOIN parties p ON (p.tenant_id,p.id)=(o.tenant_id,o.party_id) WHERE o.tenant_id=:t AND o.public_id=:p'''+suffix),{'t':t,'p':str(p)}).first()
    def _order(self,r):
        if not r:return None
        rows=self.db_session.execute(text('''SELECT l.*,COALESCE(u.public_id,o.public_id) target_public_id,p.public_id price_public_id FROM r1_restaurant_order_lines l LEFT JOIN atomic_units u ON l.target_type='atomic_unit' AND (u.tenant_id,u.id)=(l.tenant_id,l.atomic_unit_id) LEFT JOIN so1_offers o ON l.target_type='offer' AND (o.tenant_id,o.id)=(l.tenant_id,l.offer_id) JOIN so1_prices p ON p.id=l.price_id WHERE l.tenant_id=:t AND l.order_id=:o ORDER BY l.id'''),{'t':r.tenant_id,'o':r.id}).all()
        lines=tuple(OrderLine(UUID(str(x.public_id)),x.tenant_id,UUID(str(r.public_id)),TargetType(x.target_type),UUID(str(x.target_public_id)),UUID(str(x.price_public_id)),Decimal(x.quantity),Decimal(x.unit_price_snapshot),x.currency,x.note,x.row_version) for x in rows)
        return RestaurantOrder(UUID(str(r.public_id)),r.tenant_id,r.order_code,r.mode_code,r.source_channel_code,OrderStatus(r.lifecycle_status),r.opened_at,r.submitted_at,r.cancelled_at,UUID(str(r.session_public_id)) if r.session_public_id else None,UUID(str(r.party_public_id)) if r.party_public_id else None,self._staff_read('r1_restaurant_order_staff','order_id',r.tenant_id,r.id),lines,r.row_version)
    def open_order(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'open_order')
        if replay.result_public_id:return self.order(c.tenant_id,replay.result_public_id)
        m=self._mode_row(c.tenant_id,code=c.mode_code,lock=True);sid=None
        if c.session_public_id:
            s=self._session_row(c.tenant_id,c.session_public_id,True)
            if not s or s.lifecycle_status!='open':return None
            sid=s.id
        if self.db_session.execute(text('SELECT 1 FROM r1_restaurant_orders WHERE tenant_id=:t AND order_code=:c'),{'t':c.tenant_id,'c':c.order_code}).scalar():return None
        row=self.db_session.execute(text("INSERT INTO r1_restaurant_orders(public_id,tenant_id,order_code,service_mode_id,source_channel_code,lifecycle_status,opened_at,service_session_id,party_id) VALUES(:p,:t,:c,:m,:src,'open',:at,:s,:party) RETURNING id"),{'p':str(p),'t':c.tenant_id,'c':c.order_code,'m':m.id,'src':c.source_channel_code,'at':c.opened_at,'s':sid,'party':self._party_id(c.tenant_id,c.party_public_id)}).one();self._staff_insert('r1_restaurant_order_staff','order_id',c.tenant_id,row.id,c.staff);self.db_session.execute(text("INSERT INTO r1_restaurant_order_history(tenant_id,order_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:o,'opened','open','opened',:at,'{}'::jsonb)"),{'t':c.tenant_id,'o':row.id,'at':c.opened_at});self._done(c.tenant_id,c.command_key,'restaurant_order',p);return self.order(c.tenant_id,p)
    def order(self,t,p):return self._order(self._order_row(t,p))
    def add_line(self,c,p,price,currency,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'add_line')
        if replay.completed_at:return self.order(c.tenant_id,c.order_public_id)
        o=self._order_row(c.tenant_id,c.order_public_id,True)
        if not o or o.row_version!=c.expected_order_version or o.lifecycle_status!='open':return None
        table='atomic_units' if c.target_type is TargetType.ATOMIC_UNIT else 'so1_offers';target=self.db_session.execute(text(f'SELECT id FROM {table} WHERE tenant_id=:t AND public_id=:p'),{'t':c.tenant_id,'p':str(c.target_public_id)}).scalar();pr=self.db_session.execute(text('SELECT id FROM so1_prices WHERE tenant_id=:t AND public_id=:p'),{'t':c.tenant_id,'p':str(c.price_public_id)}).scalar()
        if target is None or pr is None:return None
        au=target if c.target_type is TargetType.ATOMIC_UNIT else None;offer=target if c.target_type is TargetType.OFFER else None
        self.db_session.execute(text('INSERT INTO r1_restaurant_order_lines(public_id,tenant_id,order_id,target_type,atomic_unit_id,offer_id,price_id,quantity,unit_price_snapshot,currency,note) VALUES(:p,:t,:o,:tt,:u,:offer,:price,:q,:snap,:cur,:note)'),{'p':str(p),'t':c.tenant_id,'o':o.id,'tt':c.target_type.value,'u':au,'offer':offer,'price':pr,'q':c.quantity,'snap':price,'cur':currency,'note':c.note});self.db_session.execute(text('UPDATE r1_restaurant_orders SET row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:o AND row_version=:v'),{'t':c.tenant_id,'o':o.id,'v':c.expected_order_version});self.db_session.execute(text("INSERT INTO r1_restaurant_order_history(tenant_id,order_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:o,'item_added','open','open','item_added',:at,CAST(:p AS jsonb))"),{'t':c.tenant_id,'o':o.id,'at':c.occurred_at,'p':json.dumps({'line_public_id':str(p)},sort_keys=True)});self._done(c.tenant_id,c.command_key,'restaurant_order',c.order_public_id);return self.order(c.tenant_id,c.order_public_id)
    def submit_order(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'submit_order')
        if replay.result_public_id:return self.order(c.tenant_id,replay.result_public_id)
        o=self._order_row(c.tenant_id,c.order_public_id,True)
        if not o or o.row_version!=c.expected_version or o.lifecycle_status!='open' or not self.db_session.execute(text('SELECT 1 FROM r1_restaurant_order_lines WHERE tenant_id=:t AND order_id=:o LIMIT 1'),{'t':c.tenant_id,'o':o.id}).scalar():return None
        self.db_session.execute(text("UPDATE r1_restaurant_orders SET lifecycle_status='submitted',submitted_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:o AND row_version=:v"),{'at':c.occurred_at,'t':c.tenant_id,'o':o.id,'v':c.expected_version});self.db_session.execute(text("INSERT INTO r1_restaurant_order_history(tenant_id,order_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:o,'submitted','open','submitted','submitted',:at,'{}'::jsonb)"),{'t':c.tenant_id,'o':o.id,'at':c.occurred_at});self._done(c.tenant_id,c.command_key,'restaurant_order',c.order_public_id);return self.order(c.tenant_id,c.order_public_id)
    def cancel_order(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'cancel_order')
        if replay.result_public_id:return self.order(c.tenant_id,replay.result_public_id)
        o=self._order_row(c.tenant_id,c.order_public_id,True)
        if not o or o.row_version!=c.expected_version or o.lifecycle_status not in {'open','submitted'}:return None
        self.db_session.execute(text("UPDATE r1_restaurant_orders SET lifecycle_status='cancelled',cancelled_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:o AND row_version=:v"),{'at':c.occurred_at,'t':c.tenant_id,'o':o.id,'v':c.expected_version});self.db_session.execute(text("INSERT INTO r1_restaurant_order_history(tenant_id,order_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:o,'cancelled',:f,'cancelled',:r,:at,'{}'::jsonb)"),{'t':c.tenant_id,'o':o.id,'f':o.lifecycle_status,'r':c.reason_code,'at':c.occurred_at});self._done(c.tenant_id,c.command_key,'restaurant_order',c.order_public_id);return self.order(c.tenant_id,c.order_public_id)
    def _tab_row(self,t,p,lock=False):
        suffix=' FOR UPDATE OF x' if lock else ''
        return self.db_session.execute(text('''SELECT x.*,s.public_id session_public_id,p.public_id party_public_id FROM r1_restaurant_tabs x LEFT JOIN r1_restaurant_service_sessions s ON (s.tenant_id,s.id)=(x.tenant_id,x.service_session_id) LEFT JOIN parties p ON (p.tenant_id,p.id)=(x.tenant_id,x.party_id) WHERE x.tenant_id=:t AND x.public_id=:p'''+suffix),{'t':t,'p':str(p)}).first()
    def _tab(self,r):
        if not r:return None
        orders=tuple(UUID(str(x.public_id)) for x in self.db_session.execute(text('SELECT o.public_id FROM r1_restaurant_tab_orders x JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(x.tenant_id,x.order_id) WHERE x.tenant_id=:t AND x.tab_id=:id ORDER BY x.id'),{'t':r.tenant_id,'id':r.id}).all())
        return RestaurantTab(UUID(str(r.public_id)),r.tenant_id,r.tab_code,TabStatus(r.lifecycle_status),r.opened_at,r.closed_at,UUID(str(r.session_public_id)) if r.session_public_id else None,UUID(str(r.party_public_id)) if r.party_public_id else None,orders,r.partition_version,r.row_version)
    def open_tab(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'open_tab')
        if replay.result_public_id:return self.tab(c.tenant_id,replay.result_public_id)
        sid=None
        if c.session_public_id:
            s=self._session_row(c.tenant_id,c.session_public_id,True)
            if not s or s.lifecycle_status!='open':return None
            sid=s.id
        if self.db_session.execute(text('SELECT 1 FROM r1_restaurant_tabs WHERE tenant_id=:t AND tab_code=:c'),{'t':c.tenant_id,'c':c.tab_code}).scalar():return None
        row=self.db_session.execute(text("INSERT INTO r1_restaurant_tabs(public_id,tenant_id,tab_code,lifecycle_status,opened_at,service_session_id,party_id) VALUES(:p,:t,:c,'open',:at,:s,:party) RETURNING id"),{'p':str(p),'t':c.tenant_id,'c':c.tab_code,'at':c.opened_at,'s':sid,'party':self._party_id(c.tenant_id,c.party_public_id)}).one();self.db_session.execute(text("INSERT INTO r1_restaurant_tab_history(tenant_id,tab_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:id,'opened','open','opened',:at,'{}'::jsonb)"),{'t':c.tenant_id,'id':row.id,'at':c.opened_at});self._done(c.tenant_id,c.command_key,'restaurant_tab',p);return self.tab(c.tenant_id,p)
    def tab(self,t,p):return self._tab(self._tab_row(t,p))
    def attach_order(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'attach_order')
        if replay.completed_at:return self.tab(c.tenant_id,c.tab_public_id)
        tab=self._tab_row(c.tenant_id,c.tab_public_id,True);o=self._order_row(c.tenant_id,c.order_public_id,True)
        if not tab or tab.row_version!=c.expected_tab_version or tab.lifecycle_status!='open' or not o or o.lifecycle_status=='cancelled':return None
        if self.db_session.execute(text('SELECT 1 FROM r1_restaurant_tab_orders WHERE tenant_id=:t AND order_id=:o'),{'t':c.tenant_id,'o':o.id}).scalar():return None
        self.db_session.execute(text('INSERT INTO r1_restaurant_tab_orders(tenant_id,tab_id,order_id,attached_at) VALUES(:t,:tab,:o,:at)'),{'t':c.tenant_id,'tab':tab.id,'o':o.id,'at':c.occurred_at});self.db_session.execute(text('UPDATE r1_restaurant_tabs SET row_version=row_version+1,partition_version=0,updated_at=now() WHERE tenant_id=:t AND id=:tab AND row_version=:v'),{'t':c.tenant_id,'tab':tab.id,'v':c.expected_tab_version});self._done(c.tenant_id,c.command_key,'restaurant_tab',c.tab_public_id);return self.tab(c.tenant_id,c.tab_public_id)
    def tab_line_quantities(self,t,p):
        tab=self._tab_row(t,p)
        if not tab:return {}
        rows=self.db_session.execute(text('''SELECT l.public_id,l.quantity FROM r1_restaurant_tab_orders x JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(x.tenant_id,x.order_id) JOIN r1_restaurant_order_lines l ON (l.tenant_id,l.order_id)=(o.tenant_id,o.id) WHERE x.tenant_id=:t AND x.tab_id=:tab AND o.lifecycle_status<>'cancelled' ORDER BY l.id'''),{'t':t,'tab':tab.id}).all();return {UUID(str(x.public_id)):Decimal(x.quantity) for x in rows}
    def partition_tab(self,c,ids,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'partition_tab')
        if replay.completed_at:return self.tab(c.tenant_id,c.tab_public_id),()
        tab=self._tab_row(c.tenant_id,c.tab_public_id,True)
        if not tab or tab.row_version!=c.expected_tab_version or tab.lifecycle_status!='open':return None
        lineids={UUID(str(x.public_id)):x.id for x in self.db_session.execute(text('''SELECT l.id,l.public_id FROM r1_restaurant_tab_orders x JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(x.tenant_id,x.order_id) JOIN r1_restaurant_order_lines l ON (l.tenant_id,l.order_id)=(o.tenant_id,o.id) WHERE x.tenant_id=:t AND x.tab_id=:tab AND o.lifecycle_status<>'cancelled' '''),{'t':c.tenant_id,'tab':tab.id}).all()};version=tab.partition_version+1;out=[]
        for spec,pub in zip(c.partitions,ids):
            part=self.db_session.execute(text('INSERT INTO r1_restaurant_tab_partitions(public_id,tenant_id,tab_id,partition_version,partition_code,created_at) VALUES(:p,:t,:tab,:v,:c,:at) RETURNING id'),{'p':str(pub),'t':c.tenant_id,'tab':tab.id,'v':version,'c':spec.partition_code,'at':c.occurred_at}).one()
            for a in spec.allocations:self.db_session.execute(text('INSERT INTO r1_restaurant_tab_partition_lines(tenant_id,partition_id,order_line_id,quantity) VALUES(:t,:p,:l,:q)'),{'t':c.tenant_id,'p':part.id,'l':lineids[a.line_public_id],'q':a.quantity})
            out.append(TabPartition(pub,c.tenant_id,c.tab_public_id,version,spec.partition_code,spec.allocations))
        self.db_session.execute(text('UPDATE r1_restaurant_tabs SET partition_version=:pv,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:tab AND row_version=:v'),{'pv':version,'t':c.tenant_id,'tab':tab.id,'v':c.expected_tab_version});self.db_session.execute(text("INSERT INTO r1_restaurant_tab_history(tenant_id,tab_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:tab,'partition_requested','open','open','partition_requested',:at,CAST(:p AS jsonb))"),{'t':c.tenant_id,'tab':tab.id,'at':c.occurred_at,'p':json.dumps({'partition_version':version},sort_keys=True)});self._done(c.tenant_id,c.command_key,'restaurant_tab',c.tab_public_id);return self.tab(c.tenant_id,c.tab_public_id),tuple(out)
    def close_tab(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,'close_tab')
        if replay.result_public_id:return self.tab(c.tenant_id,replay.result_public_id)
        tab=self._tab_row(c.tenant_id,c.tab_public_id,True)
        if not tab or tab.row_version!=c.expected_version or tab.lifecycle_status!='open':return None
        self.db_session.execute(text("UPDATE r1_restaurant_tabs SET lifecycle_status='closed',closed_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:tab AND row_version=:v"),{'at':c.occurred_at,'t':c.tenant_id,'tab':tab.id,'v':c.expected_version});self._done(c.tenant_id,c.command_key,'restaurant_tab',c.tab_public_id);return self.tab(c.tenant_id,c.tab_public_id)
