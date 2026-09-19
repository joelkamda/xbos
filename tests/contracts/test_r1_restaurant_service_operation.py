from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path
import json
import pytest

from restaurant.r1.contracts import *
from restaurant.r1.service import R1Authority,R1Error

class FakeRepo:
    def __init__(self):
        self.mode_rows={};self.profiles={};self.sessions={};self.orders={};self.tabs={};self.line_qty={}
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
    assert contract['read_permissions']=={
        'mode':'restaurant.service_mode.read',
        'modes':'restaurant.service_mode.read',
    }
    boundary=contract['service_mode_public_read']
    assert boundary=={
        'application_interface_completed':True,
        'tenant_scoped':True,
        'authorization_before_result':True,
        'cross_tenant_disclosure':False,
        'read_side_effects':False,
    }
