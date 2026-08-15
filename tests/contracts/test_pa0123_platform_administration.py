from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from platform_admin import *
from platform_admin.service import PlatformAdministrationError

NOW = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)


class TenantGateway:
    def __init__(self): self.states = {1: "active", 2: "active", 3: "suspended", 4: "retired"}
    def tenant_lifecycle(self, tenant_id): return self.states.get(tenant_id)


class ReadinessGateway:
    def __init__(self, fail=None): self.fail = fail
    def assess(self, **kwargs):
        codes=("pc1_tenant_available","pk_template_pinned","pc4_entitlements_effective","pc5_tenant_admin_ready")
        return {c: ("fail" if c == self.fail else "pass", f"evidence:{c}") for c in codes}


class Repo:
    def __init__(self):
        self.merchants={}; self.plans={}; self.subscriptions={}; self.usage={}; self.onboardings={}; self.commands={}
    def _cmd(self,scope,key,fp):
        old=self.commands.get((scope,key))
        if old is not None and old != fp: raise PlatformAdministrationError("PA_COMMAND_CONFLICT")
        self.commands[(scope,key)]=fp
    def register_merchant(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp)
        return self.merchants.setdefault(c.tenant_id,MerchantAdministrationRecord(uuid4(),c.tenant_id,MerchantAdministrationState.REGISTERED,1,c.external_reference))
    def merchant(self,t): return self.merchants.get(t)
    def transition_merchant(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp); old=self.merchants[c.tenant_id]
        if old.row_version!=c.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        self.merchants[c.tenant_id]=replace(old,state=c.target,row_version=old.row_version+1); return self.merchants[c.tenant_id]
    def register_plan(self,c,fp,canonical,sha):
        self._cmd("plans",c.command_key,fp); p=c.plan; key=(p.plan_code,p.version)
        old=self.plans.get(key)
        if old and old.plan_sha256!=sha: raise PlatformAdministrationError("PA_PLAN_VERSION_IMMUTABLE")
        rec=old or PlanVersionRecord(uuid4(),p.plan_code,p.version,sha,p.entitlement_codes,p.quotas); self.plans[key]=rec; return rec
    def plan(self,c,v): return self.plans.get((c,v))
    def plan_quotas(self,c,v): return self.plans[(c,v)].quotas
    def start_subscription(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp)
        if c.tenant_id in self.subscriptions: return self.subscriptions[c.tenant_id]
        p=self.plans[(c.plan_code,c.version)]
        r=SubscriptionRecord(uuid4(),c.tenant_id,c.plan_code,c.version,SubscriptionStatus.PENDING,1,c.starts_at,c.ends_at,p.entitlement_codes); self.subscriptions[c.tenant_id]=r; return r
    def subscription(self,t): return self.subscriptions.get(t)
    def transition_subscription(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp); old=self.subscriptions[c.tenant_id]
        if old.row_version!=c.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        self.subscriptions[c.tenant_id]=replace(old,status=c.target,row_version=old.row_version+1); return self.subscriptions[c.tenant_id]
    def record_usage(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp); key=(c.tenant_id,c.event_key)
        old=self.usage.get(key)
        if old is not None: return old
        r=UsageRecord(uuid4(),c.tenant_id,c.event_key,c.meter_code,c.quantity,c.period_key,c.occurred_at); self.usage[key]=r; return r
    def usage_total(self,t,m,p): return sum((r.quantity for (tenant,_),r in self.usage.items() if tenant==t and r.meter_code==m and r.period_key==p),Decimal("0"))
    def start_onboarding(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp); old=self.merchants[c.tenant_id]; self.merchants[c.tenant_id]=replace(old,state=MerchantAdministrationState.ONBOARDING,row_version=old.row_version+1)
        r=OnboardingRecord(uuid4(),c.tenant_id,c.template_code,c.template_version,c.plan_code,c.plan_version,OnboardingStatus.IN_PROGRESS,1,None,()); self.onboardings[c.tenant_id]=r; return r
    def onboarding(self,t): return self.onboardings.get(t)
    def evaluate_readiness(self,c,fp,checks,sha):
        self._cmd(c.tenant_id,c.command_key,fp); old=self.onboardings[c.tenant_id]
        if old.row_version!=c.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        status=OnboardingStatus.READY if all(x.status is ReadinessStatus.PASS for x in checks) else OnboardingStatus.BLOCKED
        self.onboardings[c.tenant_id]=replace(old,status=status,row_version=old.row_version+1,readiness_sha256=sha,checks=checks); return self.onboardings[c.tenant_id]
    def complete_onboarding(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp); old=self.onboardings[c.tenant_id]
        if old.row_version!=c.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        self.onboardings[c.tenant_id]=replace(old,status=OnboardingStatus.COMPLETED,row_version=old.row_version+1)
        m=self.merchants[c.tenant_id]; self.merchants[c.tenant_id]=replace(m,state=MerchantAdministrationState.READY,row_version=m.row_version+1)
        return self.onboardings[c.tenant_id]


def authority(fail=None): return PlatformAdministrationAuthority(Repo(),TenantGateway(),ReadinessGateway(fail))

def plan(): return PlanDefinition("neutral.standard","1.0.0","platform_admin",("platform.core","reports.basic"),(PlanQuota("api_calls",Decimal("10")),))

def bootstrap(a):
    a.register_merchant(RegisterMerchant("merchant",1))
    a.register_plan(RegisterPlanVersion("plan",plan()))
    s=a.start_subscription(StartSubscription("sub",1,"neutral.standard","1.0.0",NOW))
    return a.transition_subscription(TransitionSubscription("sub-active",1,SubscriptionStatus.ACTIVE,s.row_version,"contract active"))


def test_pa0_merchant_state_is_separate_and_governed():
    a=authority(); m=a.register_merchant(RegisterMerchant("m",1)); assert m.state is MerchantAdministrationState.REGISTERED
    with pytest.raises(PlatformAdministrationError,match="PA_INVALID_MERCHANT_TRANSITION"):
        a.transition_merchant(TransitionMerchant("x",1,MerchantAdministrationState.OPERATIONAL,m.row_version,"skip"))


def test_tenant_lifecycle_is_consumed_not_redefined():
    a=authority()
    with pytest.raises(PlatformAdministrationError,match="PA_TENANT_UNAVAILABLE"): a.register_merchant(RegisterMerchant("m",4))


def test_plan_is_immutable_and_entitlement_projection_is_not_runtime_entitlement():
    a=authority(); bootstrap(a)
    assert a.commercial_entitlement_projection(1)==("platform.core","reports.basic")
    assert a.repository.plan("neutral.standard","1.0.0").plan_sha256


def test_subscription_lifecycle_and_exact_replay():
    a=authority(); a.register_merchant(RegisterMerchant("m",1)); a.register_plan(RegisterPlanVersion("p",plan()))
    cmd=StartSubscription("s",1,"neutral.standard","1.0.0",NOW); one=a.start_subscription(cmd); two=a.start_subscription(cmd); assert one==two
    with pytest.raises(PlatformAdministrationError,match="PA_COMMAND_CONFLICT"):
        a.start_subscription(StartSubscription("s",1,"neutral.standard","1.0.0",NOW.replace(hour=10)))


def test_usage_is_immutable_evidence_and_quota_is_derived():
    a=authority(); bootstrap(a)
    a.record_usage(RecordUsage("u1",1,"event-1","api_calls",Decimal("7"),"2026-08",NOW,"api"))
    a.record_usage(RecordUsage("u2",1,"event-2","api_calls",Decimal("5"),"2026-08",NOW,"api"))
    q=a.quota_status(1,"api_calls","2026-08"); assert q.used==Decimal("12") and q.limit==Decimal("10") and q.exceeded


def test_unknown_meter_fails_closed():
    a=authority(); bootstrap(a)
    with pytest.raises(PlatformAdministrationError,match="PA_METER_NOT_DECLARED_BY_PLAN"):
        a.record_usage(RecordUsage("u",1,"e","seats",Decimal("1"),"2026-08",NOW,"api"))


def test_secret_material_rejected_from_usage_metadata():
    a=authority(); bootstrap(a)
    with pytest.raises(PlatformAdministrationError,match="PA_SECRET_MATERIAL_FORBIDDEN"):
        a.record_usage(RecordUsage("u",1,"e","api_calls",Decimal("1"),"2026-08",NOW,"api",{"api_key":"x"}))


def test_onboarding_requires_active_subscription():
    a=authority(); a.register_merchant(RegisterMerchant("m",1)); a.register_plan(RegisterPlanVersion("p",plan()))
    with pytest.raises(PlatformAdministrationError,match="PA_ACTIVE_SUBSCRIPTION_REQUIRED"):
        a.start_onboarding(StartOnboarding("o",1,"neutral.payments_only","1.0.0","neutral.standard","1.0.0"))


def test_readiness_consumes_exact_external_authority_checks():
    a=authority(); bootstrap(a); o=a.start_onboarding(StartOnboarding("o",1,"neutral.payments_only","1.0.0","neutral.standard","1.0.0"))
    ready=a.evaluate_readiness(EvaluateReadiness("r",1,o.row_version)); assert ready.status is OnboardingStatus.READY and len(ready.checks)==4
    done=a.complete_onboarding(CompleteOnboarding("c",1,ready.row_version)); assert done.status is OnboardingStatus.COMPLETED and a.repository.merchant(1).state is MerchantAdministrationState.READY


def test_failed_readiness_blocks_completion():
    a=authority("pc4_entitlements_effective"); bootstrap(a); o=a.start_onboarding(StartOnboarding("o",1,"neutral.payments_only","1.0.0","neutral.standard","1.0.0")); blocked=a.evaluate_readiness(EvaluateReadiness("r",1,o.row_version)); assert blocked.status is OnboardingStatus.BLOCKED
    with pytest.raises(PlatformAdministrationError,match="PA_ONBOARDING_NOT_READY"): a.complete_onboarding(CompleteOnboarding("c",1,blocked.row_version))


def test_ready_merchant_can_become_operational_only_after_completed_onboarding():
    a=authority(); bootstrap(a); o=a.start_onboarding(StartOnboarding("o",1,"neutral.payments_only","1.0.0","neutral.standard","1.0.0")); r=a.evaluate_readiness(EvaluateReadiness("r",1,o.row_version)); a.complete_onboarding(CompleteOnboarding("c",1,r.row_version)); m=a.repository.merchant(1); live=a.transition_merchant(TransitionMerchant("live",1,MerchantAdministrationState.OPERATIONAL,m.row_version,"go live approved")); assert live.state is MerchantAdministrationState.OPERATIONAL


def test_same_command_key_is_tenant_scoped():
    a=authority(); one=a.register_merchant(RegisterMerchant("same",1)); two=a.register_merchant(RegisterMerchant("same",2)); assert one.tenant_id!=two.tenant_id
