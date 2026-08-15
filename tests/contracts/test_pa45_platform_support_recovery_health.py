from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from platform_admin.pa45_contracts import *
from platform_admin.pa45_service import PA45Authority, PA45AuthorityError

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)


class Security:
    def __init__(self, allow=True): self.allow=allow
    def authorize_support(self, **kwargs): return self.allow, "pc5:evidence:approved" if self.allow else "pc5:evidence:denied"


class Health:
    def __init__(self, merchant=None, platform=None):
        self.merchant = {
            "tenant_context": ("healthy", "pc1:tenant", NOW),
            "subscription": ("healthy", "pa:subscription", NOW),
            "template": ("healthy", "pk:template", NOW),
        } if merchant is None else merchant
        self.platform = {
            "database": ("healthy", "ops:database", NOW),
            "migrations": ("healthy", "ops:migrations", NOW),
        } if platform is None else platform
    def assess_merchant(self, **kwargs): return self.merchant
    def assess_platform(self): return self.platform


class Repo:
    def __init__(self):
        self.merchants={1,2}; self.commands={}; self.sessions={}; self.actions={}; self.cases={}; self.recovery_actions={}; self.health=[]
    def _cmd(self,scope,key,fp,kind):
        old=self.commands.get((scope,key))
        if old is not None and old!=(fp,kind): raise PA45AuthorityError("PA45_COMMAND_CONFLICT")
        self.commands[(scope,key)]=(fp,kind)
    def merchant_exists(self,t): return t in self.merchants
    def open_support_session(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"support")
        key=(c.tenant_id,c.command_key)
        if key not in self.sessions:
            self.sessions[key]=SupportSessionRecord(uuid4(),c.tenant_id,c.actor_identity_id,c.access_mode,c.scopes,c.reason,SupportSessionState.ACTIVE,1,c.starts_at,c.expires_at,c.authorization_reference,c.step_up_reference,c.break_glass_evidence_reference)
        return self.sessions[key]
    def support_session(self,t,p):
        return next((x for x in self.sessions.values() if x.tenant_id==t and x.public_id==p),None)
    def transition_support_session(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"transition_support")
        old=self.support_session(c.tenant_id,c.support_session_id)
        if old.row_version!=c.expected_row_version: raise PA45AuthorityError("PA45_CONCURRENT_CHANGE")
        new=replace(old,state=c.target,row_version=old.row_version+1)
        for k,v in list(self.sessions.items()):
            if v==old:self.sessions[k]=new
        return new
    def record_support_action(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"support_action")
        key=(c.tenant_id,c.command_key)
        return self.actions.setdefault(key,SupportActionRecord(uuid4(),c.tenant_id,c.support_session_id,c.action_code,c.target_reference,c.evidence_reference,c.occurred_at))
    def open_recovery_case(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"recovery_case")
        k=(c.tenant_id,c.case_key)
        old=self.cases.get(k)
        if old is None:
            old=RecoveryCaseRecord(uuid4(),c.tenant_id,c.case_key,c.problem_code,c.subject_reference,c.reason,c.opened_by_identity_id,c.evidence_reference,RecoveryCaseState.OPEN,1); self.cases[k]=old
        return old
    def recovery_case(self,t,p): return next((x for x in self.cases.values() if x.tenant_id==t and x.public_id==p),None)
    def record_recovery_action(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"recovery_action")
        k=(c.tenant_id,c.command_key)
        return self.recovery_actions.setdefault(k,RecoveryActionRecord(uuid4(),c.tenant_id,c.recovery_case_id,c.support_session_id,c.action_code,c.outcome,c.evidence_reference,c.occurred_at))
    def transition_recovery_case(self,c,fp):
        self._cmd(c.tenant_id,c.command_key,fp,"transition_recovery")
        old=self.recovery_case(c.tenant_id,c.recovery_case_id)
        if old.row_version!=c.expected_row_version: raise PA45AuthorityError("PA45_CONCURRENT_CHANGE")
        new=replace(old,state=c.target,row_version=old.row_version+1)
        for k,v in list(self.cases.items()):
            if v==old:self.cases[k]=new
        return new
    def capture_health(self,key,fp,scope,t,status,checks):
        command_scope=t if t is not None else "platform"
        self._cmd(command_scope,key,fp,f"health:{scope}")
        old=next((x for x in self.health if x.scope_type==scope and x.tenant_id==t and getattr(x,'_key',None)==key),None)
        if old:return old
        import hashlib,json
        sha=hashlib.sha256(json.dumps([(c.check_code,c.status.value,c.evidence_reference,c.observed_at.isoformat()) for c in checks]).encode()).hexdigest()
        rec=HealthSnapshotRecord(uuid4(),scope,t,status,sha,checks,NOW)
        object.__setattr__(rec,'_key',key); self.health.append(rec); return rec
    def latest_health(self,scope,t):
        rows=[x for x in self.health if x.scope_type==scope and x.tenant_id==t]
        return rows[-1] if rows else None


def authority(allow=True,health=None): return PA45Authority(Repo(),Security(allow),health or Health(),now_provider=lambda:NOW)

def support_cmd(key="support",tenant=1,mode=SupportAccessMode.DELEGATED,**kw):
    return OpenSupportSession(key,tenant,kw.get("actor",uuid4()),mode,kw.get("scopes",("merchant.read","diagnostics.read")),kw.get("reason","support case"),kw.get("starts",NOW),kw.get("expires",NOW+timedelta(hours=2)),kw.get("auth","pc5:auth:1"),kw.get("step"),kw.get("bg"),kw.get("metadata",{}))


def test_delegated_support_requires_pc5_authorization_and_is_bounded():
    a=authority(); s=a.open_support_session(support_cmd()); assert s.state is SupportSessionState.ACTIVE
    with pytest.raises(PA45AuthorityError,match="PA45_SUPPORT_NOT_AUTHORIZED"): authority(False).open_support_session(support_cmd())
    with pytest.raises(PA45AuthorityError,match="PA45_DELEGATED_DURATION_EXCEEDED"): a.open_support_session(support_cmd("long",expires=NOW+timedelta(hours=9)))


def test_break_glass_requires_step_up_and_evidence_and_short_window():
    a=authority()
    with pytest.raises(PA45AuthorityError,match="PA45_BREAK_GLASS_EVIDENCE_REQUIRED"): a.open_support_session(support_cmd(mode=SupportAccessMode.BREAK_GLASS,expires=NOW+timedelta(minutes=30)))
    s=a.open_support_session(support_cmd("bg",mode=SupportAccessMode.BREAK_GLASS,expires=NOW+timedelta(minutes=30),step="pc5:stepup",bg="incident:123")); assert s.access_mode is SupportAccessMode.BREAK_GLASS


def test_support_action_requires_active_unexpired_tenant_scoped_session():
    a=authority(); s=a.open_support_session(support_cmd())
    action=a.record_support_action(RecordSupportAction("act",1,s.public_id,"inspect_config","merchant:1","audit:1",NOW+timedelta(minutes=5))); assert action.tenant_id==1
    with pytest.raises(PA45AuthorityError,match="PA45_SUPPORT_SESSION_NOT_FOUND"): a.record_support_action(RecordSupportAction("x",2,s.public_id,"inspect_config","merchant:1","audit:2",NOW))
    with pytest.raises(PA45AuthorityError,match="PA45_SUPPORT_SESSION_EXPIRED"): a.record_support_action(RecordSupportAction("late",1,s.public_id,"inspect_config","merchant:1","audit:3",NOW+timedelta(hours=3)))


def test_support_replay_and_changed_replay_conflict():
    a=authority(); cmd=support_cmd(actor=uuid4()); one=a.open_support_session(cmd); two=a.open_support_session(cmd); assert one==two
    with pytest.raises(PA45AuthorityError,match="PA45_COMMAND_CONFLICT"): a.open_support_session(replace(cmd,reason="changed"))


def test_support_session_close_is_versioned_and_terminal():
    a=authority(); s=a.open_support_session(support_cmd()); closed=a.transition_support_session(TransitionSupportSession("close",1,s.public_id,SupportSessionState.CLOSED,s.row_version,"case finished")); assert closed.state is SupportSessionState.CLOSED
    with pytest.raises(PA45AuthorityError,match="PA45_INVALID_SUPPORT_TRANSITION"): a.transition_support_session(TransitionSupportSession("again",1,s.public_id,SupportSessionState.REVOKED,closed.row_version,"no"))


def test_recovery_case_is_administrative_evidence_not_business_truth():
    a=authority(); case=a.open_recovery_case(OpenRecoveryCase("case",1,"INC-1","onboarding_stuck","onboarding:1","resume diagnosis",uuid4(),"ticket:1")); assert case.state is RecoveryCaseState.OPEN
    action=a.record_recovery_action(RecordRecoveryAction("ra",1,case.public_id,"rebuild_read_model",RecoveryActionOutcome.SUCCEEDED,"run:1",NOW)); assert action.outcome is RecoveryActionOutcome.SUCCEEDED


def test_recovery_action_with_support_session_requires_active_session():
    a=authority(); s=a.open_support_session(support_cmd()); case=a.open_recovery_case(OpenRecoveryCase("case",1,"INC-1","integration_uncertain","provider:1","diagnose",uuid4(),"ticket:1"))
    a.record_recovery_action(RecordRecoveryAction("ra",1,case.public_id,"provider_lookup",RecoveryActionOutcome.INCONCLUSIVE,"provider:lookup",NOW,s.public_id))
    a.transition_support_session(TransitionSupportSession("close",1,s.public_id,SupportSessionState.CLOSED,s.row_version,"done"))
    with pytest.raises(PA45AuthorityError,match="PA45_SUPPORT_SESSION_INACTIVE"): a.record_recovery_action(RecordRecoveryAction("late",1,case.public_id,"provider_lookup",RecoveryActionOutcome.RECORDED,"provider:2",NOW,s.public_id))


def test_recovery_resolution_is_terminal_and_versioned():
    a=authority(); case=a.open_recovery_case(OpenRecoveryCase("case",1,"INC-1","config_drift","pc4:key","repair",uuid4(),"ticket:1")); done=a.transition_recovery_case(TransitionRecoveryCase("resolve",1,case.public_id,RecoveryCaseState.RESOLVED,case.row_version,"fixed","audit:fixed")); assert done.state is RecoveryCaseState.RESOLVED
    with pytest.raises(PA45AuthorityError,match="PA45_RECOVERY_CASE_NOT_OPEN"): a.record_recovery_action(RecordRecoveryAction("after",1,case.public_id,"mutate","recorded","x",NOW))


def test_merchant_health_is_derived_and_worst_status_wins():
    h=Health(merchant={"tenant_context":("healthy","pc1",NOW),"integrations":("degraded","so8",NOW),"finance":("healthy","finance",NOW)})
    a=authority(health=h); snap=a.capture_merchant_health(CaptureMerchantHealth("health",1)); assert snap.status is HealthStatus.DEGRADED and a.latest_merchant_health(1)==snap


def test_platform_health_is_separate_from_merchant_health():
    a=authority(); p=a.capture_platform_health(CapturePlatformHealth("platform-health")); m=a.capture_merchant_health(CaptureMerchantHealth("merchant-health",1)); assert p.scope_type=="platform" and p.tenant_id is None and m.scope_type=="merchant" and m.tenant_id==1


def test_health_requires_evidence_and_never_accepts_empty_checks():
    with pytest.raises(PA45AuthorityError,match="PA45_HEALTH_CHECKS_REQUIRED"): authority(health=Health(merchant={})).capture_merchant_health(CaptureMerchantHealth("h",1))
    bad=Health(merchant={"database":("healthy","",NOW)})
    with pytest.raises(PA45AuthorityError,match="PA45_HEALTH_EVIDENCE_REQUIRED"): authority(health=bad).capture_merchant_health(CaptureMerchantHealth("h",1))


def test_secret_material_is_rejected_from_support_and_recovery_metadata():
    a=authority()
    with pytest.raises(PA45AuthorityError,match="PA45_SECRET_MATERIAL_FORBIDDEN"): a.open_support_session(support_cmd(metadata={"api_key":"secret"}))
