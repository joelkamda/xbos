"""Real canonical PC5/PC3/PK/SO1 service composition, bounded TEST doubles.

No synthetic PC5 flag accepted; genuine PC5 repository/issuer is still a field
admission hold. This tests a canonical application-service boundary, NOT a
production Web route or authoritative Finance account installation.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from uuid import UUID

import pytest

from core.platform.security_authority.contracts import (
    ActorType, Lifecycle, PermissionDefinition, ScopeType, SessionContext,
    StructuralScope,
)
from core.platform.security_authority.service import SecurityAuthority
from core.platform.semantics.contracts import (
    SemanticConcept, SemanticLifecycle, SemanticVersion,
)
from core.platform.semantics.service import SemanticAuthority
from pack_platform.contracts import (
    PackKind, PackStatus, PackVersionRecord, TenantPackState,
)
from pack_platform.service import PackAuthority
from shared_operations.so1.contracts import AtomicUnit
from shared_operations.so1.service import SO1Authority

from restaurant.g4a_canonical_product_publication import (
    CanonicalProductError, CanonicalProductPublisher, CanonicalPublish,
    CanonicalPublishProof, FinanceAccountBinding, ProductReviewSnapshot,
    ProductState, ZonePriceDraft,
)

WHEN=datetime(2026,11,23,9,0,tzinfo=timezone.utc)
PRODUCT=UUID("aaaaaaaa-0000-4000-8000-000000000017")
ATOMIC=UUID("bbbbbbbb-0000-4000-8000-000000000017")
SESSION=UUID("cccccccc-0000-4000-8000-000000000017")
CLASS_CONCEPT=UUID("dddddddd-0000-4000-8000-000000000017")
PACK_PUBLIC=UUID("eeeeeeee-0000-4000-8000-000000000017")


class IdentityRepo:
    allow=True
    revoked=False
    identity_id=200
    tenant=920002
    def permission(self,code):
        return PermissionDefinition(code,"restaurant","product","publish",
                                    allowed_scopes=(ScopeType.LOCATION,),
                                    required_assurance=1) if code=="restaurant.product.publish" else None
    def session(self,session_id):
        return SessionContext(1,SESSION,self.identity_id,self.tenant,
                              ActorType.HUMAN,2,WHEN-timedelta(minutes=5),
                              WHEN+timedelta(hours=1),
                              WHEN if self.revoked else None) if session_id==SESSION else None
    def membership_active(self,identity_id,tenant_id,at):
        return self.allow and tenant_id==self.tenant and identity_id==self.identity_id
    def assignments(self,identity_id,tenant_id,at,actor_type):
        return ({"permissions":{"restaurant.product.publish"},
                 "scope":StructuralScope(ScopeType.LOCATION,1)},) if self.allow else ()
    def policy(self,*args):return None
    def step_up_assurance(self,*args):return 0


class SemanticRepo:
    valid=True
    version=2
    def resolve(self,qualified_code,effective_on,tenant_id):
        if not self.valid:return None
        concept=SemanticConcept(11,CLASS_CONCEPT,5,
                      "industry.restaurant","soft_drink",SemanticLifecycle.ACTIVE)
        version=SemanticVersion(42,CLASS_CONCEPT,concept.id,self.version,
                  date(2024,1,1),None,"Soft drink","Beverage","a"*64)
        return concept,version


class PackRepo:
    active=True
    tenant=920002
    def state(self,tenant_id,pack_code):
        return TenantPackState(PACK_PUBLIC,self.tenant,pack_code,"1.0.0",
                 PackStatus.ACTIVE if self.active else PackStatus.DISABLED,4,True)


class So1Repo:
    valid=True
    version=3
    tenant=920002
    def atomic_unit(self,tenant_id,public_id):
        return AtomicUnit(1,public_id,self.tenant,"TEST-DRINK-01","Soft Drink",
                          "BOTTLE",self.valid,{},self.version)


class Store:
    def __init__(self):
        self.lock=Lock()
        self.current=ProductReviewSnapshot(
            PRODUCT,920002,1,100,ATOMIC,3,"industry.restaurant:soft_drink",
            2,"wnd.restaurant","1.0.0",3,ProductState.REVIEW,
            (ZonePriceDraft("MAIN",1700,2),ZonePriceDraft("VIP",2300,2),
             ZonePriceDraft("BAR",1900,2)))
        self.audit=[]
        self.fail_commit=False
    @contextmanager
    def transaction(self):
        with self.lock:
            original=self.current
            old_audit=list(self.audit)
            try:yield self
            except Exception:
                self.current=original
                self.audit=old_audit
                raise
    def load_for_update(self,tenant_id,location_id,product_public_id):
        s=self.current
        return s if s and (s.tenant_id,s.location_id,s.public_id)==(
          tenant_id,location_id,product_public_id) else None
    def publish_cas(self,*,snapshot,reviewer_identity_id,expected_revision,
                    expected_price_revisions,pack_manifest_sha256,
                    pc3_semantic_version,so1_atomic_unit_version,
                    finance_binding_version,correlation_id):
        if self.fail_commit:return None
        if (snapshot != self.current or self.current.status is not ProductState.REVIEW
            or self.current.revision!=expected_revision
            or tuple(z.row_version for z in self.current.prices)!=expected_price_revisions):
            return None
        self.current=replace(self.current,revision=expected_revision+1,
                             status=ProductState.PUBLISHED)
        self.audit.append((reviewer_identity_id,correlation_id))
        return CanonicalPublishProof(
           snapshot.tenant_id,snapshot.location_id,snapshot.public_id,
           expected_revision+1,reviewer_identity_id,pc3_semantic_version,
           pack_manifest_sha256,so1_atomic_unit_version,
           finance_binding_version,expected_price_revisions)


def build():
    i,sem,pk,so,store=IdentityRepo(),SemanticRepo(),PackRepo(),So1Repo(),Store()
    control={"finance":True,"pack_version":True}
    def pack_version(code,version):
        if not control["pack_version"]:return None
        return PackVersionRecord(PACK_PUBLIC,code,version,"pk",
                                 PackKind.INDUSTRY,"a"*64,True)
    def finance(tenant,location,atomic):
        if not control["finance"]:return None
        return FinanceAccountBinding(tenant,location,atomic,
               "REV-BEVERAGES","INV-DRINKS","COGS-DRINKS","TAX-ZERO",8,True)
    publisher=CanonicalProductPublisher(
      security=SecurityAuthority(i),semantics=SemanticAuthority(sem),
      packs=PackAuthority(pk),
      so1=SO1Authority(so,authorize=lambda *a:True,
        validate_scope=lambda *a:True,public_id_factory=lambda:ATOMIC),
      pack_version=pack_version,finance_binding=finance,store=store)
    command=CanonicalPublish(920002,1,PRODUCT,SESSION,3,(2,2,2),WHEN,
                             "G4A-TEST-CORRELATION")
    return publisher,command,i,sem,pk,so,store,control


def test_canonical_pc5_pc3_pk_so1_finance_reviewer_publishes_atomically():
    app,c,i,sem,pk,so,store,ctrl=build()
    result=app.publish(c)
    assert result.committed_revision==4
    assert result.reviewer_identity_id==200
    assert result.pc3_semantic_version==2
    assert result.finance_binding_version==8
    assert result.price_revisions==(2,2,2)
    assert not result.official_finance_posted and not result.payments_executed
    assert store.current.status is ProductState.PUBLISHED
    assert store.audit==[(200,"G4A-TEST-CORRELATION")]


@pytest.mark.parametrize("fault,error",[
  ("pc5_revoked","G4A_REAL_PC5_DENIED_OR_NOT_ADMITTED"),
  ("pc5_denied","G4A_REAL_PC5_DENIED_OR_NOT_ADMITTED"),
  ("same_actor","G4A_INDEPENDENT_REVIEWER_REQUIRED"),
  ("pc5_wrong_tenant","G4A_REAL_PC5_DENIED_OR_NOT_ADMITTED"),
  ("pk_revoked","G4A_CANONICAL_PACK_NOT_ACTIVE"),
  ("pk_wrong_tenant","G4A_CANONICAL_PACK_NOT_ACTIVE"),
  ("pk_no_manifest","G4A_PACK_MANIFEST_VERSION_NOT_VERIFIED"),
  ("pc3_missing","G4A_CANONICAL_AUTHORITY_OR_TRANSACTION_UNAVAILABLE"),
  ("pc3_changed_version","G4A_PC3_CLASSIFICATION_NOT_EFFECTIVE"),
  ("so1_disabled","G4A_SO1_ATOMIC_UNIT_STALE"),
  ("so1_changed_version","G4A_SO1_ATOMIC_UNIT_STALE"),
  ("finance_missing","G4A_FINANCE_ACCOUNT_MAPPING_NOT_CERTIFIED"),
  ("source_stale","G4A_SOURCE_REVISION_OR_STATE_STALE"),
  ("price_stale","G4A_PRICE_REVISION_OR_FORMAT_STALE"),
  ("wrong_branch","G4A_PRODUCT_SCOPE_NOT_FOUND"),
  ("failed_cas","G4A_CANONICAL_ATOMIC_PUBLICATION_FAILED"),
 ])
def test_each_missing_canonical_authority_fails_closed_and_rolls_back(fault,error):
    app,c,i,sem,pk,so,store,control=build()
    if fault=="pc5_revoked":i.revoked=True
    if fault=="pc5_denied":i.allow=False
    if fault=="same_actor":store.current=replace(store.current,creator_identity_id=200)
    if fault=="pc5_wrong_tenant":i.tenant=9
    if fault=="pk_revoked":pk.active=False
    if fault=="pk_wrong_tenant":pk.tenant=9
    if fault=="pk_no_manifest":control["pack_version"]=False
    if fault=="pc3_missing":sem.valid=False
    if fault=="pc3_changed_version":sem.version=12
    if fault=="so1_disabled":so.valid=False
    if fault=="so1_changed_version":so.version=8
    if fault=="finance_missing":control["finance"]=False
    if fault=="source_stale":c=replace(c,expected_revision=2)
    if fault=="price_stale":c=replace(c,expected_price_revisions=(2,1,2))
    if fault=="wrong_branch":c=replace(c,location_id=2)
    if fault=="failed_cas":store.fail_commit=True
    with pytest.raises(CanonicalProductError) as exc:app.publish(c)
    assert exc.value.code==error
    assert store.current.status is ProductState.REVIEW
    assert store.audit==[]


@pytest.mark.parametrize("bad",[
 lambda c:replace(c,tenant_id=0),
 lambda c:replace(c,tenant_id=True),
 lambda c:replace(c,location_id=0),
 lambda c:replace(c,expected_revision=True),
 lambda c:replace(c,expected_price_revisions=(True,2,2)),
 lambda c:replace(c,expected_price_revisions=(2,2)),
 lambda c:replace(c,occurred_at=datetime(2026,11,23,9)),
 lambda c:replace(c,correlation_id=""),
 ])
def test_command_cannot_weaken_transaction_scope(bad):
    app,c,_,_,_,_,store,_=build()
    with pytest.raises(CanonicalProductError,match="G4A_PUBLISH_COMMAND_INVALID"):
        app.publish(bad(c))
    assert not store.audit


def test_concurrent_same_product_only_one_publish():
    app,c,*_=build()
    store=_[4]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:outcome(app,c),(1,2)))
    assert sorted(outcomes)==["G4A_SOURCE_REVISION_OR_STATE_STALE","PASS"]
    assert len(store.audit)==1


def outcome(app,c):
    try:app.publish(c);return "PASS"
    except CanonicalProductError as exc:return exc.code


def test_requires_actual_canonical_service_objects_not_caller_flags():
    _,_,_,_,_,_,store,_=build()
    with pytest.raises(CanonicalProductError,match="G4A_CANONICAL_AUTHORITY_IMPLEMENTATIONS_REQUIRED"):
        CanonicalProductPublisher(
          security=True,semantics=True,packs=True,so1=True,
          pack_version=lambda *a:None,finance_binding=lambda *a:None,store=store)
