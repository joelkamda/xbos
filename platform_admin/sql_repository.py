"""PostgreSQL repository for PA0-PA3 administration authority."""
from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from sqlalchemy import text

from .contracts import *
from .service import PlatformAdministrationError, _primitive


class SQLPlatformAdministrationRepository:
    def __init__(self, session):
        self.session = session

    def _command(self, scope: str, command_key: str, fingerprint: str, command_type: str):
        if not str(command_key).strip():
            raise PlatformAdministrationError("PA_COMMAND_KEY_REQUIRED")
        self.session.execute(text("""INSERT INTO pa_commands(scope_key,command_key,request_fingerprint,command_type)
            VALUES(:s,:k,:f,:t) ON CONFLICT(scope_key,command_key) DO NOTHING"""), {"s":scope,"k":command_key,"f":fingerprint,"t":command_type})
        row=self.session.execute(text("SELECT * FROM pa_commands WHERE scope_key=:s AND command_key=:k FOR UPDATE"),{"s":scope,"k":command_key}).first()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise PlatformAdministrationError("PA_COMMAND_CONFLICT")
        return row

    def _complete(self, scope, command_key, table, result_id):
        self.session.execute(text("UPDATE pa_commands SET result_table=:t,result_id=:i,completed_at=COALESCE(completed_at,now()) WHERE scope_key=:s AND command_key=:k"),{"t":table,"i":result_id,"s":scope,"k":command_key})

    def register_merchant(self, command: RegisterMerchant, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"register_merchant")
        if replay.result_id: return self._merchant_by_id(replay.result_id)
        existing=self.session.execute(text("SELECT id FROM pa_merchants WHERE tenant_id=:t"),{"t":command.tenant_id}).first()
        if existing:
            self._complete(scope,command.command_key,"pa_merchants",existing.id); return self._merchant_by_id(existing.id)
        row=self.session.execute(text("""INSERT INTO pa_merchants(tenant_id,administration_state,external_reference)
            VALUES(:t,'registered',:e) RETURNING id"""),{"t":command.tenant_id,"e":command.external_reference}).one()
        self.session.execute(text("""INSERT INTO pa_merchant_history(tenant_id,merchant_id,sequence,from_state,to_state,command_key,reason)
            VALUES(:t,:m,1,NULL,'registered',:k,'merchant registered')"""),{"t":command.tenant_id,"m":row.id,"k":command.command_key})
        self._complete(scope,command.command_key,"pa_merchants",row.id); return self._merchant_by_id(row.id)

    def merchant(self, tenant_id:int):
        row=self.session.execute(text("SELECT id FROM pa_merchants WHERE tenant_id=:t"),{"t":tenant_id}).first()
        return None if row is None else self._merchant_by_id(row.id)

    def _merchant_by_id(self, item_id:int):
        r=self.session.execute(text("SELECT * FROM pa_merchants WHERE id=:i"),{"i":item_id}).one()
        return MerchantAdministrationRecord(r.public_id,r.tenant_id,MerchantAdministrationState(r.administration_state),r.row_version,r.external_reference)

    def transition_merchant(self, command:TransitionMerchant, fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"transition_merchant")
        if replay.result_id:return self._merchant_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_merchants WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).first()
        if row is None: raise PlatformAdministrationError("PA_MERCHANT_NOT_FOUND")
        if row.row_version!=command.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        self.session.execute(text("UPDATE pa_merchants SET administration_state=:s,row_version=row_version+1,updated_at=now() WHERE id=:i"),{"s":command.target.value,"i":row.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_merchant_history WHERE tenant_id=:t AND merchant_id=:m"),{"t":command.tenant_id,"m":row.id}).scalar_one()
        self.session.execute(text("""INSERT INTO pa_merchant_history(tenant_id,merchant_id,sequence,from_state,to_state,command_key,reason)
            VALUES(:t,:m,:q,:f,:to,:k,:r)"""),{"t":command.tenant_id,"m":row.id,"q":seq,"f":row.administration_state,"to":command.target.value,"k":command.command_key,"r":command.reason})
        self._complete(scope,command.command_key,"pa_merchants",row.id); return self._merchant_by_id(row.id)

    def register_plan(self, command:RegisterPlanVersion, fingerprint:str, canonical:str, sha:str):
        scope="platform:plans"; replay=self._command(scope,command.command_key,fingerprint,"register_plan")
        if replay.result_id:return self._plan_by_id(replay.result_id)
        p=command.plan
        root=self.session.execute(text("SELECT * FROM pa_plans WHERE plan_code=:c"),{"c":p.plan_code}).first()
        if root is None:
            root=self.session.execute(text("INSERT INTO pa_plans(plan_code,owner_code) VALUES(:c,:o) RETURNING *"),{"c":p.plan_code,"o":p.owner_code}).one()
        elif root.owner_code!=p.owner_code: raise PlatformAdministrationError("PA_PLAN_OWNER_CONFLICT")
        existing=self.session.execute(text("SELECT id,plan_sha256 FROM pa_plan_versions WHERE plan_id=:p AND plan_version=:v"),{"p":root.id,"v":p.version}).first()
        if existing:
            if existing.plan_sha256!=sha: raise PlatformAdministrationError("PA_PLAN_VERSION_IMMUTABLE")
            self._complete(scope,command.command_key,"pa_plan_versions",existing.id); return self._plan_by_id(existing.id)
        row=self.session.execute(text("""INSERT INTO pa_plan_versions(plan_id,plan_version,plan_json,plan_sha256,entitlement_codes)
            VALUES(:p,:v,CAST(:j AS jsonb),:s,:e) RETURNING id"""),{"p":root.id,"v":p.version,"j":canonical,"s":sha,"e":list(p.entitlement_codes)}).one()
        for q in p.quotas:
            self.session.execute(text("INSERT INTO pa_plan_quotas(plan_version_id,meter_code,quota_limit) VALUES(:i,:m,:l)"),{"i":row.id,"m":q.meter_code,"l":q.limit})
        self._complete(scope,command.command_key,"pa_plan_versions",row.id); return self._plan_by_id(row.id)

    def plan(self, code, version):
        row=self.session.execute(text("""SELECT v.id FROM pa_plan_versions v JOIN pa_plans p ON p.id=v.plan_id
            WHERE p.plan_code=:c AND v.plan_version=:v"""),{"c":code,"v":version}).first()
        return None if row is None else self._plan_by_id(row.id)

    def _plan_by_id(self,item_id):
        r=self.session.execute(text("""SELECT v.*,p.plan_code FROM pa_plan_versions v JOIN pa_plans p ON p.id=v.plan_id WHERE v.id=:i"""),{"i":item_id}).one()
        return PlanVersionRecord(r.public_id,r.plan_code,r.plan_version,r.plan_sha256,tuple(r.entitlement_codes or ()),self.plan_quotas(r.plan_code,r.plan_version))

    def plan_quotas(self, code, version):
        rows=self.session.execute(text("""SELECT q.meter_code,q.quota_limit FROM pa_plan_quotas q JOIN pa_plan_versions v ON v.id=q.plan_version_id JOIN pa_plans p ON p.id=v.plan_id
            WHERE p.plan_code=:c AND v.plan_version=:v ORDER BY q.meter_code"""),{"c":code,"v":version}).all()
        return tuple(PlanQuota(r.meter_code,Decimal(r.quota_limit)) for r in rows)

    def start_subscription(self, command:StartSubscription, fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"start_subscription")
        if replay.result_id:return self._subscription_by_id(replay.result_id)
        if self.session.execute(text("SELECT 1 FROM pa_subscriptions WHERE tenant_id=:t"),{"t":command.tenant_id}).first(): raise PlatformAdministrationError("PA_SUBSCRIPTION_ALREADY_EXISTS")
        pv=self.session.execute(text("""SELECT v.id FROM pa_plan_versions v JOIN pa_plans p ON p.id=v.plan_id WHERE p.plan_code=:c AND v.plan_version=:v"""),{"c":command.plan_code,"v":command.version}).one()
        row=self.session.execute(text("""INSERT INTO pa_subscriptions(tenant_id,plan_version_id,status,starts_at,ends_at)
            VALUES(:t,:p,'pending',:s,:e) RETURNING id"""),{"t":command.tenant_id,"p":pv.id,"s":command.starts_at,"e":command.ends_at}).one()
        self.session.execute(text("INSERT INTO pa_subscription_history(tenant_id,subscription_id,sequence,from_status,to_status,command_key,reason) VALUES(:t,:i,1,NULL,'pending',:k,'subscription created')"),{"t":command.tenant_id,"i":row.id,"k":command.command_key})
        self._complete(scope,command.command_key,"pa_subscriptions",row.id); return self._subscription_by_id(row.id)

    def subscription(self, tenant_id):
        row=self.session.execute(text("SELECT id FROM pa_subscriptions WHERE tenant_id=:t"),{"t":tenant_id}).first()
        return None if row is None else self._subscription_by_id(row.id)

    def _subscription_by_id(self,item_id):
        r=self.session.execute(text("""SELECT s.*,p.plan_code,v.plan_version,v.entitlement_codes FROM pa_subscriptions s JOIN pa_plan_versions v ON v.id=s.plan_version_id JOIN pa_plans p ON p.id=v.plan_id WHERE s.id=:i"""),{"i":item_id}).one()
        return SubscriptionRecord(r.public_id,r.tenant_id,r.plan_code,r.plan_version,SubscriptionStatus(r.status),r.row_version,r.starts_at,r.ends_at,tuple(r.entitlement_codes or ()))

    def transition_subscription(self,command:TransitionSubscription,fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"transition_subscription")
        if replay.result_id:return self._subscription_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_subscriptions WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).first()
        if row is None: raise PlatformAdministrationError("PA_SUBSCRIPTION_NOT_FOUND")
        if row.row_version!=command.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        self.session.execute(text("UPDATE pa_subscriptions SET status=:s,row_version=row_version+1,updated_at=now() WHERE id=:i"),{"s":command.target.value,"i":row.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_subscription_history WHERE tenant_id=:t AND subscription_id=:i"),{"t":command.tenant_id,"i":row.id}).scalar_one()
        self.session.execute(text("INSERT INTO pa_subscription_history(tenant_id,subscription_id,sequence,from_status,to_status,command_key,reason) VALUES(:t,:i,:q,:f,:to,:k,:r)"),{"t":command.tenant_id,"i":row.id,"q":seq,"f":row.status,"to":command.target.value,"k":command.command_key,"r":command.reason})
        self._complete(scope,command.command_key,"pa_subscriptions",row.id); return self._subscription_by_id(row.id)

    def record_usage(self, command:RecordUsage, fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"record_usage")
        if replay.result_id:return self._usage_by_id(replay.result_id)
        existing=self.session.execute(text("SELECT id,request_fingerprint FROM pa_usage_events WHERE tenant_id=:t AND event_key=:e"),{"t":command.tenant_id,"e":command.event_key}).first()
        if existing:
            if existing.request_fingerprint!=fingerprint: raise PlatformAdministrationError("PA_USAGE_EVENT_CONFLICT")
            self._complete(scope,command.command_key,"pa_usage_events",existing.id); return self._usage_by_id(existing.id)
        row=self.session.execute(text("""INSERT INTO pa_usage_events(tenant_id,event_key,meter_code,quantity,period_key,occurred_at,source_reference,metadata_json,request_fingerprint)
            VALUES(:t,:e,:m,:q,:p,:o,:s,CAST(:j AS jsonb),:f) RETURNING id"""),{"t":command.tenant_id,"e":command.event_key,"m":command.meter_code,"q":command.quantity,"p":command.period_key,"o":command.occurred_at,"s":command.source_reference,"j":json.dumps(_primitive(command.metadata),sort_keys=True),"f":fingerprint}).one()
        self._complete(scope,command.command_key,"pa_usage_events",row.id); return self._usage_by_id(row.id)

    def _usage_by_id(self,item_id):
        r=self.session.execute(text("SELECT * FROM pa_usage_events WHERE id=:i"),{"i":item_id}).one()
        return UsageRecord(r.public_id,r.tenant_id,r.event_key,r.meter_code,Decimal(r.quantity),r.period_key,r.occurred_at)

    def usage_total(self,tenant_id,meter_code,period_key):
        value=self.session.execute(text("SELECT COALESCE(sum(quantity),0) FROM pa_usage_events WHERE tenant_id=:t AND meter_code=:m AND period_key=:p"),{"t":tenant_id,"m":meter_code,"p":period_key}).scalar_one()
        return Decimal(value)

    def start_onboarding(self,command:StartOnboarding,fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"start_onboarding")
        if replay.result_id:return self._onboarding_by_id(replay.result_id)
        if self.session.execute(text("SELECT 1 FROM pa_onboarding_runs WHERE tenant_id=:t"),{"t":command.tenant_id}).first(): raise PlatformAdministrationError("PA_ONBOARDING_ALREADY_EXISTS")
        merchant=self.session.execute(text("SELECT * FROM pa_merchants WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).one()
        if merchant.administration_state!='registered': raise PlatformAdministrationError("PA_MERCHANT_NOT_REGISTERED")
        plan=self.session.execute(text("""SELECT v.id FROM pa_plan_versions v JOIN pa_plans p ON p.id=v.plan_id WHERE p.plan_code=:c AND v.plan_version=:v"""),{"c":command.plan_code,"v":command.plan_version}).one()
        row=self.session.execute(text("""INSERT INTO pa_onboarding_runs(tenant_id,template_code,template_version,plan_version_id,status)
            VALUES(:t,:c,:v,:p,'in_progress') RETURNING id"""),{"t":command.tenant_id,"c":command.template_code,"v":command.template_version,"p":plan.id}).one()
        self.session.execute(text("UPDATE pa_merchants SET administration_state='onboarding',row_version=row_version+1,updated_at=now() WHERE id=:i"),{"i":merchant.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_merchant_history WHERE tenant_id=:t AND merchant_id=:m"),{"t":command.tenant_id,"m":merchant.id}).scalar_one()
        self.session.execute(text("INSERT INTO pa_merchant_history(tenant_id,merchant_id,sequence,from_state,to_state,command_key,reason) VALUES(:t,:m,:q,'registered','onboarding',:k,'onboarding started')"),{"t":command.tenant_id,"m":merchant.id,"q":seq,"k":command.command_key})
        self._complete(scope,command.command_key,"pa_onboarding_runs",row.id); return self._onboarding_by_id(row.id)

    def onboarding(self,tenant_id):
        row=self.session.execute(text("SELECT id FROM pa_onboarding_runs WHERE tenant_id=:t"),{"t":tenant_id}).first()
        return None if row is None else self._onboarding_by_id(row.id)

    def evaluate_readiness(self,command:EvaluateReadiness,fingerprint:str,checks:tuple[ReadinessCheck,...],readiness_sha:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"evaluate_readiness")
        if replay.result_id:return self._onboarding_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_onboarding_runs WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).one()
        if row.row_version!=command.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        snapshot=self.session.execute(text("SELECT COALESCE(max(snapshot_sequence),0)+1 FROM pa_onboarding_checks WHERE tenant_id=:t AND onboarding_id=:i"),{"t":command.tenant_id,"i":row.id}).scalar_one()
        for check in checks:
            self.session.execute(text("INSERT INTO pa_onboarding_checks(tenant_id,onboarding_id,snapshot_sequence,check_code,status,evidence_reference) VALUES(:t,:i,:q,:c,:s,:e)"),{"t":command.tenant_id,"i":row.id,"q":snapshot,"c":check.check_code,"s":check.status.value,"e":check.evidence_reference})
        target='ready' if all(c.status is ReadinessStatus.PASS for c in checks) else 'blocked'
        self.session.execute(text("UPDATE pa_onboarding_runs SET status=:s,row_version=row_version+1,readiness_sha256=:r,updated_at=now() WHERE id=:i"),{"s":target,"r":readiness_sha,"i":row.id})
        self._complete(scope,command.command_key,"pa_onboarding_runs",row.id); return self._onboarding_by_id(row.id)

    def complete_onboarding(self,command:CompleteOnboarding,fingerprint:str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"complete_onboarding")
        if replay.result_id:return self._onboarding_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_onboarding_runs WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).one()
        if row.row_version!=command.expected_row_version: raise PlatformAdministrationError("PA_CONCURRENT_CHANGE")
        if row.status!='ready': raise PlatformAdministrationError("PA_ONBOARDING_NOT_READY")
        merchant=self.session.execute(text("SELECT * FROM pa_merchants WHERE tenant_id=:t FOR UPDATE"),{"t":command.tenant_id}).one()
        self.session.execute(text("UPDATE pa_onboarding_runs SET status='completed',row_version=row_version+1,completed_at=now(),updated_at=now() WHERE id=:i"),{"i":row.id})
        self.session.execute(text("UPDATE pa_merchants SET administration_state='ready',row_version=row_version+1,updated_at=now() WHERE id=:i"),{"i":merchant.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_merchant_history WHERE tenant_id=:t AND merchant_id=:m"),{"t":command.tenant_id,"m":merchant.id}).scalar_one()
        self.session.execute(text("INSERT INTO pa_merchant_history(tenant_id,merchant_id,sequence,from_state,to_state,command_key,reason) VALUES(:t,:m,:q,:f,'ready',:k,'onboarding completed')"),{"t":command.tenant_id,"m":merchant.id,"q":seq,"f":merchant.administration_state,"k":command.command_key})
        self._complete(scope,command.command_key,"pa_onboarding_runs",row.id); return self._onboarding_by_id(row.id)

    def _onboarding_by_id(self,item_id):
        r=self.session.execute(text("""SELECT o.*,p.plan_code,v.plan_version FROM pa_onboarding_runs o JOIN pa_plan_versions v ON v.id=o.plan_version_id JOIN pa_plans p ON p.id=v.plan_id WHERE o.id=:i"""),{"i":item_id}).one()
        snapshot=self.session.execute(text("SELECT COALESCE(max(snapshot_sequence),0) FROM pa_onboarding_checks WHERE onboarding_id=:i"),{"i":item_id}).scalar_one()
        checks=()
        if snapshot:
            rows=self.session.execute(text("SELECT check_code,status,evidence_reference FROM pa_onboarding_checks WHERE onboarding_id=:i AND snapshot_sequence=:s ORDER BY check_code"),{"i":item_id,"s":snapshot}).all()
            checks=tuple(ReadinessCheck(x.check_code,ReadinessStatus(x.status),x.evidence_reference) for x in rows)
        return OnboardingRecord(r.public_id,r.tenant_id,r.template_code,r.template_version,r.plan_code,r.plan_version,OnboardingStatus(r.status),r.row_version,r.readiness_sha256,checks)
