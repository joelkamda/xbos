from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path
from dataclasses import replace
import json
import pytest

from restaurant.r1.contracts import *
from restaurant.r1.service import R1Authority,R1Error

class FakeRepo:
    def __init__(self):
        self.mode_rows={};self.profiles={};self.sessions={};self.orders={};self.tabs={};self.line_qty={};self.change_commands={};self.remove_commands={};self.removed_rows={};self.preparation_line_ids=set();self.current_partition_line_ids=set();self.historical_partition_line_ids=set();self.order_history=[]
    def define_mode(self,c,p,fp):
        key=(c.tenant_id,c.mode_code)
        if key in self.mode_rows:return self.mode_rows[key]
        x=ServiceMode(p,c.tenant_id,c.mode_code,c.display_name,c.requires_session,c.requires_resource,c.supports_tabs,c.supports_reservations,c.allows_remote_origin,True,c.metadata,1);self.mode_rows[key]=x;return x
    def mode(self,t,c):return self.mode_rows.get((t,c))
    def modes(self,t):return tuple(x for (tenant,_),x in self.mode_rows.items() if tenant==t)
    def profile_resource(self,c,fp):
        x=ResourceProfile(c.tenant_id,c.resource_public_id,c.role,c.parent_resource_public_id,c.service_mode_codes,c.metadata);self.profiles[c.resource_public_id]=x;return x
    def resource_profile(self,t,p):return self.profiles.get(p)
    def open_session(self,c,p,fp):
        x=ServiceSession(p,c.tenant_id,c.mode_code,c.guest_count,SessionStatus.OPEN,c.opened_at,None,c.reservation_public_id,c.party_public_id,c.resource_public_ids,c.staff,1);self.sessions[p]=x;return x
    def session(self,t,p):return self.sessions.get(p)
    def close_session(self,c,fp):
        x=self.sessions.get(c.session_public_id)
        if not x or x.row_version!=c.expected_version:return None
        x=ServiceSession(x.public_id,x.tenant_id,x.mode_code,x.guest_count,SessionStatus.CLOSED,x.opened_at,c.occurred_at,x.reservation_public_id,x.party_public_id,x.resource_public_ids,x.staff,x.row_version+1);self.sessions[x.public_id]=x;return x
    def open_order(self,c,p,fp):
        x=RestaurantOrder(p,c.tenant_id,c.order_code,c.mode_code,c.source_channel_code,OrderStatus.OPEN,c.opened_at,None,None,c.session_public_id,c.party_public_id,c.staff,(),1);self.orders[p]=x;return x
    def order(self,t,p):return self.orders.get(p)
    def add_line(self,c,p,price,currency,fp):
        o=self.orders[c.order_public_id]
        if o.row_version!=c.expected_order_version or o.status is not OrderStatus.OPEN:return None
        line=OrderLine(p,c.tenant_id,o.public_id,c.target_type,c.target_public_id,c.price_public_id,c.quantity,price,currency,c.note,1)
        o=RestaurantOrder(o.public_id,o.tenant_id,o.order_code,o.mode_code,o.source_channel_code,o.status,o.opened_at,o.submitted_at,o.cancelled_at,o.session_public_id,o.party_public_id,o.staff,o.lines+(line,),o.row_version+1);self.orders[o.public_id]=o;return o
    def change_line_quantity(self,c,fp):
        key=(c.tenant_id,c.command_key)
        if key in self.change_commands:
            prior_fp,order_public_id=self.change_commands[key]
            if prior_fp!=fp:raise R1Error('R1_COMMAND_CONFLICT','idempotency_conflict','Command key already used with different content')
            return self.orders.get(order_public_id)
        o=self.orders.get(c.order_public_id)
        if not o or o.tenant_id!=c.tenant_id or o.status is not OrderStatus.OPEN or o.row_version!=c.expected_order_version:return None
        index=None
        for i,line in enumerate(o.lines):
            if line.public_id==c.order_line_public_id:
                index=i;break
        if index is None:return None
        line=o.lines[index]
        if line.tenant_id!=c.tenant_id or line.order_public_id!=o.public_id or line.row_version!=c.expected_line_version:return None
        changed=replace(line,quantity=c.quantity,row_version=line.row_version+1)
        lines=list(o.lines);lines[index]=changed
        updated=replace(o,lines=tuple(lines),row_version=o.row_version+1)
        self.orders[o.public_id]=updated
        self.change_commands[key]=(fp,o.public_id)
        self.order_history.append({'event_type':'item_quantity_changed','order_public_id':o.public_id,'line_public_id':line.public_id,'old_quantity':line.quantity,'new_quantity':changed.quantity,'old_line_version':line.row_version,'new_line_version':changed.row_version})
        return updated
    def remove_order_line(self,c,fp):
        key=(c.tenant_id,c.command_key)
        if key in self.remove_commands:
            prior_fp,order_public_id=self.remove_commands[key]
            if prior_fp!=fp:raise R1Error('R1_COMMAND_CONFLICT','idempotency_conflict','Command key already used with different content')
            return self.orders.get(order_public_id)
        o=self.orders.get(c.order_public_id)
        if not o or o.tenant_id!=c.tenant_id or o.status is not OrderStatus.OPEN or o.row_version!=c.expected_order_version:return None
        line=next((x for x in o.lines if x.public_id==c.order_line_public_id),None)
        if not line or line.tenant_id!=c.tenant_id or line.order_public_id!=o.public_id or line.row_version!=c.expected_line_version or line.lifecycle_status is not OrderLineLifecycle.ACTIVE:return None
        if line.public_id in self.preparation_line_ids or line.public_id in self.current_partition_line_ids:return None
        removed=replace(line,row_version=line.row_version+1,lifecycle_status=OrderLineLifecycle.REMOVED);self.removed_rows[line.public_id]=removed
        updated=replace(o,lines=tuple(x for x in o.lines if x.public_id!=line.public_id),row_version=o.row_version+1);self.orders[o.public_id]=updated;self.line_qty.pop(line.public_id,None)
        self.remove_commands[key]=(fp,o.public_id);self.order_history.append({'event_type':'item_removed','order_public_id':o.public_id,'line_public_id':line.public_id,'quantity':line.quantity,'unit_price_snapshot':line.unit_price_snapshot,'currency':line.currency,'old_line_version':line.row_version,'new_line_version':removed.row_version})
        return updated
    def submit_order(self,c,fp):
        o=self.orders[c.order_public_id]
        if o.row_version!=c.expected_version or not o.lines:return None
        o=RestaurantOrder(o.public_id,o.tenant_id,o.order_code,o.mode_code,o.source_channel_code,OrderStatus.SUBMITTED,o.opened_at,c.occurred_at,None,o.session_public_id,o.party_public_id,o.staff,o.lines,o.row_version+1);self.orders[o.public_id]=o;return o
    def cancel_order(self,c,fp):return None
    def open_tab(self,c,p,fp):
        x=RestaurantTab(p,c.tenant_id,c.tab_code,TabStatus.OPEN,c.opened_at,None,c.session_public_id,c.party_public_id,(),0,1);self.tabs[p]=x;return x
    def tab(self,t,p):return self.tabs.get(p)
    def attach_order(self,c,fp):
        x=self.tabs[c.tab_public_id]
        if x.row_version!=c.expected_tab_version:return None
        x=RestaurantTab(x.public_id,x.tenant_id,x.tab_code,x.status,x.opened_at,x.closed_at,x.session_public_id,x.party_public_id,x.order_public_ids+(c.order_public_id,),0,x.row_version+1);self.tabs[x.public_id]=x
        self.line_qty={l.public_id:l.quantity for l in self.orders[c.order_public_id].lines};return x
    def tab_line_quantities(self,t,p):return self.line_qty
    def partition_tab(self,c,ids,fp):
        x=self.tabs[c.tab_public_id];parts=tuple(TabPartition(pid,c.tenant_id,c.tab_public_id,x.partition_version+1,s.partition_code,s.allocations) for pid,s in zip(ids,c.partitions));x=RestaurantTab(x.public_id,x.tenant_id,x.tab_code,x.status,x.opened_at,x.closed_at,x.session_public_id,x.party_public_id,x.order_public_ids,x.partition_version+1,x.row_version+1);self.tabs[x.public_id]=x;return x,parts
    def close_tab(self,c,fp):return None

def obj(t,p,**kw):return SimpleNamespace(tenant_id=t,public_id=p,**kw)
def authority(authorize=lambda *a:True):
    repo=FakeRepo();store={}
    def resolver(t,p):return store.get((t,p))
    a=R1Authority(repo,resource_resolver=resolver,party_resolver=resolver,identity_resolver=resolver,offer_resolver=resolver,atomic_unit_resolver=resolver,price_resolver=resolver,reservation_resolver=resolver,authorize=authorize)
    return a,repo,store

def test_service_modes_are_configurable_and_tables_optional():
    a,_,_=authority();m=a.define_mode(DefineServiceMode('m1',1,'takeaway','Takeaway',allows_remote_origin=True));assert not m.requires_session and m.allows_remote_origin

def test_resource_required_mode_must_require_session():
    a,_,_=authority()
    with pytest.raises(R1Error) as e:a.define_mode(DefineServiceMode('x',1,'bad','Bad',requires_resource=True))
    assert e.value.code=='R1_RESOURCE_REQUIRES_SESSION'

def test_so5_resource_profile_not_duplicate_identity():
    a,repo,s=authority();rid=uuid4();s[(1,rid)]=obj(1,rid);a.define_mode(DefineServiceMode('m',1,'dine_in','Dine',requires_session=True,requires_resource=True,supports_tabs=True));p=a.profile_resource(ProfileResource('p',1,rid,ResourceRole.TABLE,service_mode_codes=('dine_in',)));assert p.resource_public_id==rid and repo.profiles[rid].role is ResourceRole.TABLE

def test_reservation_composition_is_optional_so10_reference():
    a,_,s=authority();res=uuid4();s[(1,res)]=obj(1,res);a.define_mode(DefineServiceMode('m',1,'dine_in','Dine',requires_session=True,supports_reservations=True));session=a.open_session(OpenSession('s',1,'dine_in',2,datetime.now(timezone.utc),reservation_public_id=res));assert session.reservation_public_id==res

def test_remote_order_policy_is_mode_driven():
    a,_,_=authority();a.define_mode(DefineServiceMode('m',1,'counter','Counter'))
    with pytest.raises(R1Error) as e:a.open_order(OpenOrder('o',1,'O1','counter','whatsapp',datetime.now(timezone.utc)))
    assert e.value.code=='R1_REMOTE_NOT_ALLOWED'

def test_staff_is_reference_not_new_staff_authority():
    a,_,s=authority();party=uuid4();ident=uuid4();s[(1,party)]=obj(1,party);s[(1,ident)]=obj(1,ident,party_public_id=party);a.define_mode(DefineServiceMode('m',1,'counter','Counter'));o=a.open_order(OpenOrder('o',1,'O1','counter','in_person',datetime.now(timezone.utc),staff=(StaffAttribution('cashier',party,ident),)));assert o.staff[0].role_code=='cashier'

def test_order_line_uses_so1_target_and_price_snapshot():
    a,repo,s=authority();target=uuid4();price=uuid4();s[(1,target)]=obj(1,target,active=True);s[(1,price)]=obj(1,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,amount=Decimal('12.50'),currency='USD');a.define_mode(DefineServiceMode('m',1,'counter','Counter'));o=a.open_order(OpenOrder('o',1,'O1','counter','in_person',datetime.now(timezone.utc)));o=a.add_line(AddLine('l',1,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('2'),datetime.now(timezone.utc)));assert o.lines[0].commercial_total==Decimal('25.00')

def test_obligation_handoff_creates_no_financial_truth():
    a,repo,s=authority();target=uuid4();price=uuid4();s[(1,target)]=obj(1,target);s[(1,price)]=obj(1,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,amount=Decimal('10'),currency='XAF');a.define_mode(DefineServiceMode('m',1,'counter','Counter'));o=a.open_order(OpenOrder('o',1,'O1','counter','in_person',datetime.now(timezone.utc)));o=a.add_line(AddLine('l',1,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('2'),datetime.now(timezone.utc)));o=a.submit_order(SubmitOrder('sub',1,o.public_id,o.row_version,datetime.now(timezone.utc)));h=a.obligation_handoff(1,o.public_id);assert h.commercial_total==Decimal('20') and h.creates_financial_truth is False and h.finance_authority=='Neutral Finance'

def test_split_partition_requires_exact_line_quantities():
    a,repo,s=authority();target=uuid4();price=uuid4();s[(1,target)]=obj(1,target);s[(1,price)]=obj(1,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,amount=Decimal('10'),currency='USD');a.define_mode(DefineServiceMode('m',1,'counter','Counter',supports_tabs=True));o=a.open_order(OpenOrder('o',1,'O1','counter','in_person',datetime.now(timezone.utc)));o=a.add_line(AddLine('l',1,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('2'),datetime.now(timezone.utc)));tab=a.open_tab(OpenTab('t',1,'T1',datetime.now(timezone.utc)));tab=a.attach_order(AttachOrder('a',1,tab.public_id,o.public_id,tab.row_version,datetime.now(timezone.utc)));p=(PartitionSpec('guest_a',(LineAllocation(o.lines[0].public_id,Decimal('1')),)),PartitionSpec('guest_b',(LineAllocation(o.lines[0].public_id,Decimal('1')),)));tab,parts=a.partition_tab(PartitionTab('p',1,tab.public_id,tab.row_version,p,datetime.now(timezone.utc)));assert len(parts)==2 and tab.partition_version==1

def test_r1_acceptance_escapes_percent_encoded_database_url_for_alembic():
    root=Path(__file__).resolve().parents[2]
    source=(root/'scripts/verify_r1_restaurant_service_operation.py').read_text(encoding='utf-8')
    assert "url.replace('%','%%')" in source

def test_partition_parent_has_tenant_scoped_unique_key_for_composite_fk():
    root=Path(__file__).resolve().parents[2]
    up=(root/'alembic_neutral/sql/r1_restaurant_service_operation_up.sql').read_text(encoding='utf-8')
    assert 'CONSTRAINT uq_r1_partition_tenant_id UNIQUE(tenant_id,id)' in up
    assert 'FOREIGN KEY(tenant_id,partition_id) REFERENCES public.r1_restaurant_tab_partitions(tenant_id,id)' in up



def test_r1_acceptance_scopes_alembic_to_disposable_database_via_environment():
    root=Path(__file__).resolve().parents[2]
    source=(root/'scripts/verify_r1_restaurant_service_operation.py').read_text(encoding='utf-8')
    assert "os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)" in source
    assert "_run(command.upgrade,cfg,test_url,HEAD)" in source
    assert "_run(command.downgrade,cfg,test_url,PREVIOUS)" in source
    assert "_run(command.upgrade,devcfg,url.render_as_string(hide_password=False),HEAD)" in source

def test_service_mode_public_read_returns_exact_normalized_tenant_mode():
    a,_,_=authority();created=a.define_mode(DefineServiceMode('m',1,' DINE_IN ','Dine'))
    read=a.mode(1,' DINE_IN ')
    assert read==created and read.mode_code=='dine_in' and read.tenant_id==1

def test_service_modes_public_read_returns_only_requested_tenant_modes():
    a,_,_=authority()
    a.define_mode(DefineServiceMode('m1',1,'counter','Counter'))
    a.define_mode(DefineServiceMode('m2',2,'delivery','Delivery',allows_remote_origin=True))
    rows=a.modes(1)
    assert tuple(x.mode_code for x in rows)==('counter',)
    assert all(x.tenant_id==1 for x in rows)

def test_service_mode_public_reads_fail_closed_without_read_permission():
    def authorize(t,p,*_):return p!='restaurant.service_mode.read'
    a,_,_=authority(authorize=authorize)
    a.define_mode(DefineServiceMode('m',1,'counter','Counter'))
    with pytest.raises(R1Error) as one:a.mode(1,'counter')
    with pytest.raises(R1Error) as many:a.modes(1)
    assert one.value.code=='R1_PERMISSION_DENIED'
    assert many.value.code=='R1_PERMISSION_DENIED'

def test_service_mode_public_read_does_not_disclose_cross_tenant_existence():
    a,_,_=authority()
    a.define_mode(DefineServiceMode('m',2,'private_mode','Private'))
    with pytest.raises(R1Error) as e:a.mode(1,'private_mode')
    assert e.value.code=='R1_MODE_NOT_FOUND' and e.value.category=='scope_mismatch'

def test_service_mode_public_reads_are_side_effect_free():
    a,repo,_=authority()
    a.define_mode(DefineServiceMode('m1',1,'counter','Counter'))
    a.define_mode(DefineServiceMode('m2',1,'takeaway','Takeaway',allows_remote_origin=True))
    before=dict(repo.mode_rows)
    one=a.mode(1,'counter');many=a.modes(1)
    assert one.mode_code=='counter' and len(many)==2
    assert repo.mode_rows==before

def test_service_mode_public_read_rejects_repository_scope_leak():
    a,repo,_=authority()
    foreign=ServiceMode(uuid4(),2,'foreign','Foreign',False,False,False,False,False,True,{},1)
    repo.mode_rows[(1,'foreign')]=foreign
    with pytest.raises(R1Error) as one:a.mode(1,'foreign')
    assert one.value.code=='R1_MODE_NOT_FOUND'
    repo.mode_rows[(2,'foreign')]=repo.mode_rows.pop((1,'foreign'))
    original=repo.mode_rows
    class LeakyRepo(FakeRepo):
        def modes(self,t):return tuple(original.values())
    leaky=LeakyRepo();leaky.mode_rows=original
    a.repo=leaky
    with pytest.raises(R1Error) as many:a.modes(1)
    assert many.value.code=='R1_MODE_SCOPE_MISMATCH'

def test_service_mode_public_interface_records_exact_read_permission_without_http_routes():
    root=Path(__file__).resolve().parents[2]
    contract=json.loads((root/'contracts/restaurant/v1/r1_public_interfaces.json').read_text(encoding='utf-8'))
    assert contract['http_routes_added'] is False
    assert contract['read_permissions']['mode']=='restaurant.service_mode.read'
    assert contract['read_permissions']['modes']=='restaurant.service_mode.read'
    assert contract['read_permissions']['order']=='restaurant.order.read'
    boundary=contract['service_mode_public_read']
    assert boundary=={
        'application_interface_completed':True,
        'tenant_scoped':True,
        'authorization_before_result':True,
        'cross_tenant_disclosure':False,
        'read_side_effects':False,
    }

def _cart_fixture(*,authorize=lambda *a:True,tenant=1):
    a,r,s=authority(authorize=authorize);now=datetime(2026,9,19,10,0,tzinfo=timezone.utc);target=uuid4();price=uuid4()
    s[(tenant,target)]=obj(tenant,target,active=True)
    s[(tenant,price)]=obj(tenant,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,amount=Decimal('1000'),currency='XAF')
    a.define_mode(DefineServiceMode('mode',tenant,'takeaway','Takeaway',allows_remote_origin=True))
    o=a.open_order(OpenOrder('open',tenant,'CART-1','takeaway','customer_channel',now))
    o=a.add_line(AddLine('add',tenant,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('2'),now))
    return a,r,s,now,o,target,price

def test_public_order_read_is_authorized_tenant_scoped_exact_and_side_effect_free():
    a,r,s,now,o,target,price=_cart_fixture();before=(dict(r.orders),list(r.order_history),dict(r.change_commands))
    read=a.order(1,o.public_id)
    assert read==o and read.lines==o.lines and read.row_version==o.row_version and read.lines[0].row_version==1
    assert sum((x.commercial_total for x in read.lines),Decimal('0'))==Decimal('2000')
    assert before==(dict(r.orders),list(r.order_history),dict(r.change_commands))

def test_public_order_read_fails_closed_before_result_and_hides_cross_tenant_existence():
    denied=lambda t,p,*_:p!='restaurant.order.read'
    a,r,s,now,o,target,price=_cart_fixture(authorize=denied)
    with pytest.raises(R1Error) as e:a.order(1,o.public_id)
    assert e.value.code=='R1_PERMISSION_DENIED'
    a2,r2,s2,now2,o2,target2,price2=_cart_fixture(tenant=2)
    with pytest.raises(R1Error) as cross:a2.order(1,o2.public_id)
    assert cross.value.code=='R1_ORDER_NOT_FOUND' and cross.value.category=='scope_mismatch'
    with pytest.raises(R1Error) as missing:a2.order(1,uuid4())
    assert missing.value.code=='R1_ORDER_NOT_FOUND'

def test_change_line_quantity_changes_only_quantity_and_versions_and_history():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0]
    changed=a.change_line_quantity(ChangeOrderLineQuantity('qty',1,o.public_id,line.public_id,o.row_version,line.row_version,Decimal('3'),now))
    after=changed.lines[0]
    assert changed.row_version==o.row_version+1 and after.row_version==line.row_version+1 and after.quantity==Decimal('3')
    assert after.target_type==line.target_type and after.target_public_id==line.target_public_id and after.price_public_id==line.price_public_id
    assert after.unit_price_snapshot==line.unit_price_snapshot and after.currency==line.currency and after.note==line.note
    assert sum((x.commercial_total for x in changed.lines),Decimal('0'))==Decimal('3000')
    assert r.order_history==[{'event_type':'item_quantity_changed','order_public_id':o.public_id,'line_public_id':line.public_id,'old_quantity':Decimal('2'),'new_quantity':Decimal('3'),'old_line_version':1,'new_line_version':2}]

def test_change_line_quantity_rejects_submitted_cancelled_zero_negative_and_stale_versions():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0]
    submitted=a.submit_order(SubmitOrder('submit',1,o.public_id,o.row_version,now))
    with pytest.raises(R1Error) as sub:a.change_line_quantity(ChangeOrderLineQuantity('q-sub',1,submitted.public_id,line.public_id,submitted.row_version,line.row_version,Decimal('3'),now))
    assert sub.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'
    a2,r2,s2,now2,o2,target2,price2=_cart_fixture();l2=o2.lines[0];r2.orders[o2.public_id]=replace(o2,status=OrderStatus.CANCELLED,cancelled_at=now2)
    with pytest.raises(R1Error) as can:a2.change_line_quantity(ChangeOrderLineQuantity('q-can',1,o2.public_id,l2.public_id,o2.row_version,l2.row_version,Decimal('3'),now2))
    assert can.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'
    for key,q in [('zero',Decimal('0')),('neg',Decimal('-1'))]:
        with pytest.raises(R1Error) as bad:a2.change_line_quantity(ChangeOrderLineQuantity(key,1,o2.public_id,l2.public_id,o2.row_version,l2.row_version,q,now2))
        assert bad.value.code=='R1_INVALID_QUANTITY'
    a3,r3,s3,now3,o3,target3,price3=_cart_fixture();l3=o3.lines[0]
    with pytest.raises(R1Error) as stale_o:a3.change_line_quantity(ChangeOrderLineQuantity('stale-o',1,o3.public_id,l3.public_id,o3.row_version-1,l3.row_version,Decimal('3'),now3))
    assert stale_o.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'
    with pytest.raises(R1Error) as stale_l:a3.change_line_quantity(ChangeOrderLineQuantity('stale-l',1,o3.public_id,l3.public_id,o3.row_version,l3.row_version+1,Decimal('3'),now3))
    assert stale_l.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'

def test_change_line_quantity_rejects_wrong_tenant_and_line_not_in_order_without_partial_effect():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0];before=replace(o)
    with pytest.raises(R1Error) as wrong_tenant:a.change_line_quantity(ChangeOrderLineQuantity('wrong-t',2,o.public_id,line.public_id,o.row_version,line.row_version,Decimal('3'),now))
    assert wrong_tenant.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'
    with pytest.raises(R1Error) as missing:a.change_line_quantity(ChangeOrderLineQuantity('missing',1,o.public_id,uuid4(),o.row_version,line.row_version,Decimal('3'),now))
    assert missing.value.code=='R1_ORDER_LINE_CHANGE_CONFLICT'
    assert r.orders[o.public_id]==before and r.order_history==[] and r.change_commands=={}

def test_change_line_quantity_idempotent_replay_is_one_effect_and_conflict_fails_closed():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0];cmd=ChangeOrderLineQuantity('qty-replay',1,o.public_id,line.public_id,o.row_version,line.row_version,Decimal('4'),now)
    first=a.change_line_quantity(cmd);second=a.change_line_quantity(cmd)
    assert first==second and first.row_version==o.row_version+1 and first.lines[0].row_version==line.row_version+1
    assert len(r.order_history)==1 and len(r.change_commands)==1
    conflict=replace(cmd,quantity=Decimal('5'))
    with pytest.raises(R1Error) as e:a.change_line_quantity(conflict)
    assert e.value.code=='R1_COMMAND_CONFLICT'
    assert len(r.order_history)==1 and r.orders[o.public_id].lines[0].quantity==Decimal('4')

def test_submit_after_quantity_change_requires_new_order_version():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0];changed=a.change_line_quantity(ChangeOrderLineQuantity('qty',1,o.public_id,line.public_id,o.row_version,line.row_version,Decimal('3'),now))
    with pytest.raises(R1Error) as stale:a.submit_order(SubmitOrder('stale-submit',1,o.public_id,o.row_version,now))
    assert stale.value.code=='R1_ORDER_STATE_CONFLICT'
    submitted=a.submit_order(SubmitOrder('fresh-submit',1,o.public_id,changed.row_version,now))
    assert submitted.status is OrderStatus.SUBMITTED

def test_c1_sql_quantity_change_preserves_price_currency_and_writes_exact_history():
    root=Path(__file__).resolve().parents[2];repo=(root/'restaurant/r1/sql_repository.py').read_text(encoding='utf-8')
    block=repo[repo.index('def change_line_quantity'):repo.index('def submit_order',repo.index('def change_line_quantity'))]
    assert 'change_order_line_quantity' in block and "item_quantity_changed" in block
    assert 'SET quantity=:q,row_version=row_version+1' in block
    assert 'unit_price_snapshot=' not in block and 'currency=' not in block and 'price_id=' not in block
    for key in ['line_public_id','old_quantity','new_quantity','old_line_version','new_line_version']:assert key in block
    assert 'FOR UPDATE' in block and 'expected_order_version' in block and 'expected_line_version' in block

def test_remove_order_line_active_cart_projection_total_handoff_and_history():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0];removed=a.remove_order_line(RemoveOrderLine('rm',1,o.public_id,line.public_id,o.row_version,line.row_version,now))
    assert removed.status is OrderStatus.OPEN and removed.lines==() and removed.row_version==o.row_version+1
    durable=r.removed_rows[line.public_id];assert durable.quantity==line.quantity and durable.unit_price_snapshot==line.unit_price_snapshot and durable.currency==line.currency and durable.lifecycle_status is OrderLineLifecycle.REMOVED and durable.row_version==line.row_version+1
    assert r.order_history[-1]=={'event_type':'item_removed','order_public_id':o.public_id,'line_public_id':line.public_id,'quantity':line.quantity,'unit_price_snapshot':line.unit_price_snapshot,'currency':line.currency,'old_line_version':line.row_version,'new_line_version':line.row_version+1}
    with pytest.raises(R1Error) as empty:a.submit_order(SubmitOrder('sub-empty',1,o.public_id,removed.row_version,now))
    assert empty.value.code=='R1_ORDER_STATE_CONFLICT'

def test_remove_order_line_authorization_state_versions_unknown_and_idempotency():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0]
    denied=lambda t,p,*_:p!='restaurant.order.remove';ad,rd,sd,nd,od,td,pd=_cart_fixture(authorize=denied);ld=od.lines[0]
    with pytest.raises(R1Error) as unauth:ad.remove_order_line(RemoveOrderLine('u',1,od.public_id,ld.public_id,od.row_version,ld.row_version,nd));assert unauth.value.code=='R1_PERMISSION_DENIED'
    for key,cmd in [('stale-o',RemoveOrderLine('stale-o',1,o.public_id,line.public_id,o.row_version-1,line.row_version,now)),('stale-l',RemoveOrderLine('stale-l',1,o.public_id,line.public_id,o.row_version,line.row_version+1,now)),('missing',RemoveOrderLine('missing',1,o.public_id,uuid4(),o.row_version,line.row_version,now)),('tenant',RemoveOrderLine('tenant',2,o.public_id,line.public_id,o.row_version,line.row_version,now))]:
        with pytest.raises(R1Error) as e:a.remove_order_line(cmd)
        assert e.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT'
    cmd=RemoveOrderLine('rm-replay',1,o.public_id,line.public_id,o.row_version,line.row_version,now);first=a.remove_order_line(cmd);second=a.remove_order_line(cmd);assert first==second and len([x for x in r.order_history if x['event_type']=='item_removed'])==1
    with pytest.raises(R1Error) as conflict:a.remove_order_line(replace(cmd,expected_line_version=line.row_version+1));assert conflict.value.code=='R1_COMMAND_CONFLICT'
    with pytest.raises(R1Error) as newcmd:a.remove_order_line(RemoveOrderLine('rm-new',1,o.public_id,line.public_id,first.row_version,line.row_version+1,now));assert newcmd.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT'

def test_remove_order_line_denies_submitted_cancelled_preparation_and_current_partition_but_allows_superseded_history():
    a,r,s,now,o,target,price=_cart_fixture();line=o.lines[0];submitted=a.submit_order(SubmitOrder('sub',1,o.public_id,o.row_version,now))
    with pytest.raises(R1Error) as sub:a.remove_order_line(RemoveOrderLine('rm-sub',1,submitted.public_id,line.public_id,submitted.row_version,line.row_version,now));assert sub.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT'
    a2,r2,s2,now2,o2,t2,p2=_cart_fixture();l2=o2.lines[0];r2.orders[o2.public_id]=replace(o2,status=OrderStatus.CANCELLED,cancelled_at=now2)
    with pytest.raises(R1Error) as can:a2.remove_order_line(RemoveOrderLine('rm-can',1,o2.public_id,l2.public_id,o2.row_version,l2.row_version,now2));assert can.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT'
    a3,r3,s3,now3,o3,t3,p3=_cart_fixture();l3=o3.lines[0];r3.preparation_line_ids.add(l3.public_id);before=r3.orders[o3.public_id]
    with pytest.raises(R1Error) as prep:a3.remove_order_line(RemoveOrderLine('rm-prep',1,o3.public_id,l3.public_id,o3.row_version,l3.row_version,now3));assert prep.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT';assert r3.orders[o3.public_id]==before and r3.order_history==[]
    a4,r4,s4,now4,o4,t4,p4=_cart_fixture();l4=o4.lines[0];r4.current_partition_line_ids.add(l4.public_id)
    with pytest.raises(R1Error) as current:a4.remove_order_line(RemoveOrderLine('rm-current',1,o4.public_id,l4.public_id,o4.row_version,l4.row_version,now4));assert current.value.code=='R1_ORDER_LINE_REMOVE_CONFLICT'
    a5,r5,s5,now5,o5,t5,p5=_cart_fixture();l5=o5.lines[0];r5.historical_partition_line_ids.add(l5.public_id);ok=a5.remove_order_line(RemoveOrderLine('rm-old',1,o5.public_id,l5.public_id,o5.row_version,l5.row_version,now5));assert ok.lines==() and l5.public_id in r5.historical_partition_line_ids

def test_removed_line_is_excluded_from_obligation_and_active_tab_quantities():
    a,r,s=authority();now=datetime.now(timezone.utc);target=uuid4();price=uuid4();s[(1,target)]=obj(1,target);s[(1,price)]=obj(1,price,target_type=SimpleNamespace(value='atomic_unit'),target_public_id=target,amount=Decimal('10'),currency='XAF');a.define_mode(DefineServiceMode('m',1,'counter','Counter',supports_tabs=True));o=a.open_order(OpenOrder('o',1,'O1','counter','in_person',now));o=a.add_line(AddLine('l1',1,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('2'),now));first=o.lines[0];o=a.add_line(AddLine('l2',1,o.public_id,o.row_version,TargetType.ATOMIC_UNIT,target,price,Decimal('3'),now));tab=a.open_tab(OpenTab('t',1,'T1',now));tab=a.attach_order(AttachOrder('a',1,tab.public_id,o.public_id,tab.row_version,now));o=a.remove_order_line(RemoveOrderLine('rm',1,o.public_id,first.public_id,o.row_version,first.row_version,now));assert first.public_id not in r.tab_line_quantities(1,tab.public_id)
    o=a.submit_order(SubmitOrder('sub',1,o.public_id,o.row_version,now));h=a.obligation_handoff(1,o.public_id);assert len(h.lines)==1 and h.commercial_total==Decimal('30') and h.lines[0].order_line_public_id!=first.public_id

def test_c2_sql_has_soft_remove_guards_and_active_only_projections():
    root=Path(__file__).resolve().parents[2];repo=(root/'restaurant/r1/sql_repository.py').read_text(encoding='utf-8');up=(root/'alembic_neutral/sql/r1_restaurant_order_line_lifecycle_up.sql').read_text(encoding='utf-8');down=(root/'alembic_neutral/sql/r1_restaurant_order_line_lifecycle_down.sql').read_text(encoding='utf-8');mig=(root/'alembic_neutral/versions/r1_restaurant_order_line_lifecycle_046.py').read_text(encoding='utf-8')
    assert 'revision = "r1_restaurant_order_line_lifecycle_046"' in mig and 'down_revision = "ia0_neutral_interaction_authority_045"' in mig
    assert "CHECK(lifecycle_status IN('active','removed'))" in up and "SET lifecycle_status='active'" in up and 'removed order-line history exists' in down
    block=repo[repo.index('def remove_order_line'):repo.index('def submit_order',repo.index('def remove_order_line'))];assert "SET lifecycle_status='removed'" in block and 'DELETE FROM r1_restaurant_order_lines' not in block and 'quantity=0' not in block
    assert 'r2_restaurant_preparation_ticket_items' in block and 'partition_version=tab.partition_version' in block and "l.lifecycle_status='active'" in repo
