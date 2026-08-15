"""PostgreSQL repository for PA4-PA5 support/recovery and health authority."""
from __future__ import annotations

import hashlib
import json
from sqlalchemy import text

from .pa45_contracts import *
from .pa45_service import PA45AuthorityError, _canonical, _primitive


class SQLPA45Repository:
    def __init__(self, session):
        self.session = session

    def _command(self, scope: str, command_key: str, fingerprint: str, command_type: str):
        if not str(command_key).strip():
            raise PA45AuthorityError("PA45_COMMAND_KEY_REQUIRED")
        self.session.execute(text("""INSERT INTO pa_commands(scope_key,command_key,request_fingerprint,command_type)
            VALUES(:s,:k,:f,:t) ON CONFLICT(scope_key,command_key) DO NOTHING"""), {"s":scope,"k":command_key,"f":fingerprint,"t":command_type})
        row = self.session.execute(text("SELECT * FROM pa_commands WHERE scope_key=:s AND command_key=:k FOR UPDATE"), {"s":scope,"k":command_key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise PA45AuthorityError("PA45_COMMAND_CONFLICT")
        return row

    def _complete(self, scope, command_key, table, result_id):
        self.session.execute(text("UPDATE pa_commands SET result_table=:t,result_id=:i,completed_at=COALESCE(completed_at,now()) WHERE scope_key=:s AND command_key=:k"), {"t":table,"i":result_id,"s":scope,"k":command_key})

    def merchant_exists(self, tenant_id: int) -> bool:
        return self.session.execute(text("SELECT 1 FROM pa_merchants WHERE tenant_id=:t"), {"t":tenant_id}).first() is not None

    def open_support_session(self, command: OpenSupportSession, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"open_support_session")
        if replay.result_id: return self._support_by_id(replay.result_id)
        row=self.session.execute(text("""INSERT INTO pa_support_sessions(
            tenant_id,actor_identity_public_id,access_mode,scopes,reason,state,starts_at,expires_at,
            authorization_reference,step_up_reference,break_glass_evidence_reference,metadata_json)
            VALUES(:t,:a,:m,:s,:r,'active',:st,:ex,:ar,:su,:bg,CAST(:j AS jsonb)) RETURNING id"""), {
            "t":command.tenant_id,"a":command.actor_identity_id,"m":command.access_mode.value,"s":list(command.scopes),"r":command.reason,
            "st":command.starts_at,"ex":command.expires_at,"ar":command.authorization_reference,"su":command.step_up_reference,
            "bg":command.break_glass_evidence_reference,"j":json.dumps(_primitive(command.metadata),sort_keys=True)}) .one()
        self.session.execute(text("""INSERT INTO pa_support_session_history(tenant_id,support_session_id,sequence,from_state,to_state,command_key,reason)
            VALUES(:t,:i,1,NULL,'active',:k,'support session opened')"""), {"t":command.tenant_id,"i":row.id,"k":command.command_key})
        self._complete(scope,command.command_key,"pa_support_sessions",row.id); return self._support_by_id(row.id)

    def support_session(self, tenant_id: int, public_id):
        row=self.session.execute(text("SELECT id FROM pa_support_sessions WHERE tenant_id=:t AND public_id=:p"), {"t":tenant_id,"p":public_id}).first()
        return None if row is None else self._support_by_id(row.id)

    def _support_by_id(self, item_id):
        r=self.session.execute(text("SELECT * FROM pa_support_sessions WHERE id=:i"), {"i":item_id}).one()
        return SupportSessionRecord(r.public_id,r.tenant_id,r.actor_identity_public_id,SupportAccessMode(r.access_mode),tuple(r.scopes or ()),r.reason,SupportSessionState(r.state),r.row_version,r.starts_at,r.expires_at,r.authorization_reference,r.step_up_reference,r.break_glass_evidence_reference)

    def transition_support_session(self, command: TransitionSupportSession, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"transition_support_session")
        if replay.result_id: return self._support_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_support_sessions WHERE tenant_id=:t AND public_id=:p FOR UPDATE"), {"t":command.tenant_id,"p":command.support_session_id}).first()
        if row is None: raise PA45AuthorityError("PA45_SUPPORT_SESSION_NOT_FOUND")
        if row.row_version != command.expected_row_version: raise PA45AuthorityError("PA45_CONCURRENT_CHANGE")
        self.session.execute(text("UPDATE pa_support_sessions SET state=:s,row_version=row_version+1,updated_at=now() WHERE id=:i"), {"s":command.target.value,"i":row.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_support_session_history WHERE tenant_id=:t AND support_session_id=:i"), {"t":command.tenant_id,"i":row.id}).scalar_one()
        self.session.execute(text("""INSERT INTO pa_support_session_history(tenant_id,support_session_id,sequence,from_state,to_state,command_key,reason)
            VALUES(:t,:i,:q,:f,:to,:k,:r)"""), {"t":command.tenant_id,"i":row.id,"q":seq,"f":row.state,"to":command.target.value,"k":command.command_key,"r":command.reason})
        self._complete(scope,command.command_key,"pa_support_sessions",row.id); return self._support_by_id(row.id)

    def record_support_action(self, command: RecordSupportAction, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"record_support_action")
        if replay.result_id: return self._support_action_by_id(replay.result_id)
        sid=self.session.execute(text("SELECT id FROM pa_support_sessions WHERE tenant_id=:t AND public_id=:p"), {"t":command.tenant_id,"p":command.support_session_id}).scalar_one_or_none()
        if sid is None: raise PA45AuthorityError("PA45_SUPPORT_SESSION_NOT_FOUND")
        row=self.session.execute(text("""INSERT INTO pa_support_actions(tenant_id,support_session_id,action_code,target_reference,evidence_reference,occurred_at,metadata_json,request_fingerprint)
            VALUES(:t,:s,:a,:r,:e,:o,CAST(:j AS jsonb),:f) RETURNING id"""), {"t":command.tenant_id,"s":sid,"a":command.action_code,"r":command.target_reference,"e":command.evidence_reference,"o":command.occurred_at,"j":json.dumps(_primitive(command.metadata),sort_keys=True),"f":fingerprint}).one()
        self._complete(scope,command.command_key,"pa_support_actions",row.id); return self._support_action_by_id(row.id)

    def _support_action_by_id(self,item_id):
        r=self.session.execute(text("""SELECT a.*,s.public_id AS support_public_id FROM pa_support_actions a JOIN pa_support_sessions s ON s.id=a.support_session_id WHERE a.id=:i"""), {"i":item_id}).one()
        return SupportActionRecord(r.public_id,r.tenant_id,r.support_public_id,r.action_code,r.target_reference,r.evidence_reference,r.occurred_at)

    def open_recovery_case(self, command: OpenRecoveryCase, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"open_recovery_case")
        if replay.result_id: return self._recovery_by_id(replay.result_id)
        existing=self.session.execute(text("SELECT id,request_fingerprint FROM pa_recovery_cases WHERE tenant_id=:t AND case_key=:k"), {"t":command.tenant_id,"k":command.case_key}).first()
        if existing:
            if existing.request_fingerprint != fingerprint: raise PA45AuthorityError("PA45_RECOVERY_CASE_CONFLICT")
            self._complete(scope,command.command_key,"pa_recovery_cases",existing.id); return self._recovery_by_id(existing.id)
        row=self.session.execute(text("""INSERT INTO pa_recovery_cases(tenant_id,case_key,problem_code,subject_reference,reason,opened_by_identity_public_id,evidence_reference,state,request_fingerprint)
            VALUES(:t,:k,:p,:s,:r,:a,:e,'open',:f) RETURNING id"""), {"t":command.tenant_id,"k":command.case_key,"p":command.problem_code,"s":command.subject_reference,"r":command.reason,"a":command.opened_by_identity_id,"e":command.evidence_reference,"f":fingerprint}).one()
        self.session.execute(text("""INSERT INTO pa_recovery_case_history(tenant_id,recovery_case_id,sequence,from_state,to_state,command_key,reason,evidence_reference)
            VALUES(:t,:i,1,NULL,'open',:k,:r,:e)"""), {"t":command.tenant_id,"i":row.id,"k":command.command_key,"r":command.reason,"e":command.evidence_reference})
        self._complete(scope,command.command_key,"pa_recovery_cases",row.id); return self._recovery_by_id(row.id)

    def recovery_case(self, tenant_id: int, public_id):
        row=self.session.execute(text("SELECT id FROM pa_recovery_cases WHERE tenant_id=:t AND public_id=:p"), {"t":tenant_id,"p":public_id}).first()
        return None if row is None else self._recovery_by_id(row.id)

    def _recovery_by_id(self,item_id):
        r=self.session.execute(text("SELECT * FROM pa_recovery_cases WHERE id=:i"), {"i":item_id}).one()
        return RecoveryCaseRecord(r.public_id,r.tenant_id,r.case_key,r.problem_code,r.subject_reference,r.reason,r.opened_by_identity_public_id,r.evidence_reference,RecoveryCaseState(r.state),r.row_version)

    def record_recovery_action(self, command: RecordRecoveryAction, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"record_recovery_action")
        if replay.result_id: return self._recovery_action_by_id(replay.result_id)
        cid=self.session.execute(text("SELECT id FROM pa_recovery_cases WHERE tenant_id=:t AND public_id=:p"), {"t":command.tenant_id,"p":command.recovery_case_id}).scalar_one_or_none()
        if cid is None: raise PA45AuthorityError("PA45_RECOVERY_CASE_NOT_FOUND")
        sid=None
        if command.support_session_id is not None:
            sid=self.session.execute(text("SELECT id FROM pa_support_sessions WHERE tenant_id=:t AND public_id=:p"), {"t":command.tenant_id,"p":command.support_session_id}).scalar_one_or_none()
            if sid is None: raise PA45AuthorityError("PA45_SUPPORT_SESSION_NOT_FOUND")
        row=self.session.execute(text("""INSERT INTO pa_recovery_actions(tenant_id,recovery_case_id,support_session_id,action_code,outcome,evidence_reference,occurred_at,metadata_json,request_fingerprint)
            VALUES(:t,:c,:s,:a,:o,:e,:at,CAST(:j AS jsonb),:f) RETURNING id"""), {"t":command.tenant_id,"c":cid,"s":sid,"a":command.action_code,"o":command.outcome.value,"e":command.evidence_reference,"at":command.occurred_at,"j":json.dumps(_primitive(command.metadata),sort_keys=True),"f":fingerprint}).one()
        self._complete(scope,command.command_key,"pa_recovery_actions",row.id); return self._recovery_action_by_id(row.id)

    def _recovery_action_by_id(self,item_id):
        r=self.session.execute(text("""SELECT a.*,c.public_id AS case_public_id,s.public_id AS support_public_id
            FROM pa_recovery_actions a JOIN pa_recovery_cases c ON c.id=a.recovery_case_id
            LEFT JOIN pa_support_sessions s ON s.id=a.support_session_id WHERE a.id=:i"""), {"i":item_id}).one()
        return RecoveryActionRecord(r.public_id,r.tenant_id,r.case_public_id,r.support_public_id,r.action_code,RecoveryActionOutcome(r.outcome),r.evidence_reference,r.occurred_at)

    def transition_recovery_case(self, command: TransitionRecoveryCase, fingerprint: str):
        scope=f"tenant:{command.tenant_id}"; replay=self._command(scope,command.command_key,fingerprint,"transition_recovery_case")
        if replay.result_id: return self._recovery_by_id(replay.result_id)
        row=self.session.execute(text("SELECT * FROM pa_recovery_cases WHERE tenant_id=:t AND public_id=:p FOR UPDATE"), {"t":command.tenant_id,"p":command.recovery_case_id}).first()
        if row is None: raise PA45AuthorityError("PA45_RECOVERY_CASE_NOT_FOUND")
        if row.row_version != command.expected_row_version: raise PA45AuthorityError("PA45_CONCURRENT_CHANGE")
        self.session.execute(text("UPDATE pa_recovery_cases SET state=:s,row_version=row_version+1,updated_at=now() WHERE id=:i"), {"s":command.target.value,"i":row.id})
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pa_recovery_case_history WHERE tenant_id=:t AND recovery_case_id=:i"), {"t":command.tenant_id,"i":row.id}).scalar_one()
        self.session.execute(text("""INSERT INTO pa_recovery_case_history(tenant_id,recovery_case_id,sequence,from_state,to_state,command_key,reason,evidence_reference)
            VALUES(:t,:i,:q,:f,:to,:k,:r,:e)"""), {"t":command.tenant_id,"i":row.id,"q":seq,"f":row.state,"to":command.target.value,"k":command.command_key,"r":command.reason,"e":command.evidence_reference})
        self._complete(scope,command.command_key,"pa_recovery_cases",row.id); return self._recovery_by_id(row.id)

    def capture_health(self, command_key: str, fingerprint: str, scope_type: str, tenant_id: int | None, status: HealthStatus, checks: tuple[HealthCheck,...]):
        scope=f"tenant:{tenant_id}" if tenant_id is not None else "platform:health"; command_type=f"capture_{scope_type}_health"
        replay=self._command(scope,command_key,fingerprint,command_type)
        if replay.result_id: return self._health_by_id(replay.result_id)
        snapshot_sha=hashlib.sha256(_canonical(checks).encode("utf-8")).hexdigest()
        row=self.session.execute(text("""INSERT INTO pa_health_snapshots(scope_type,tenant_id,status,snapshot_sha256)
            VALUES(:s,:t,:h,:f) RETURNING id"""), {"s":scope_type,"t":tenant_id,"h":status.value,"f":snapshot_sha}).one()
        for check in checks:
            self.session.execute(text("""INSERT INTO pa_health_checks(health_snapshot_id,check_code,status,evidence_reference,observed_at)
                VALUES(:i,:c,:s,:e,:o)"""), {"i":row.id,"c":check.check_code,"s":check.status.value,"e":check.evidence_reference,"o":check.observed_at})
        self._complete(scope,command_key,"pa_health_snapshots",row.id); return self._health_by_id(row.id)

    def latest_health(self, scope_type: str, tenant_id: int | None):
        if tenant_id is None:
            row=self.session.execute(text("SELECT id FROM pa_health_snapshots WHERE scope_type=:s AND tenant_id IS NULL ORDER BY recorded_at DESC,id DESC LIMIT 1"), {"s":scope_type}).first()
        else:
            row=self.session.execute(text("SELECT id FROM pa_health_snapshots WHERE scope_type=:s AND tenant_id=:t ORDER BY recorded_at DESC,id DESC LIMIT 1"), {"s":scope_type,"t":tenant_id}).first()
        return None if row is None else self._health_by_id(row.id)

    def _health_by_id(self,item_id):
        r=self.session.execute(text("SELECT * FROM pa_health_snapshots WHERE id=:i"), {"i":item_id}).one()
        rows=self.session.execute(text("SELECT check_code,status,evidence_reference,observed_at FROM pa_health_checks WHERE health_snapshot_id=:i ORDER BY check_code"), {"i":item_id}).all()
        checks=tuple(HealthCheck(x.check_code,HealthStatus(x.status),x.evidence_reference,x.observed_at) for x in rows)
        return HealthSnapshotRecord(r.public_id,r.scope_type,r.tenant_id,HealthStatus(r.status),r.snapshot_sha256,checks,r.recorded_at)
