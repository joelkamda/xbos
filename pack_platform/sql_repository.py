"""PostgreSQL persistence for PK0-PK3 pack authority."""
from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import PackAuthorityError, _primitive

class SQLPackRepository:
    def __init__(self,session):self.session=session
    def _command(self,scope,key,fingerprint,kind):
        self.session.execute(text("""INSERT INTO pk_pack_commands(scope_key,command_key,request_fingerprint,command_type)
            VALUES(:s,:k,:f,:t) ON CONFLICT(scope_key,command_key) DO NOTHING"""),{"s":scope,"k":key,"f":fingerprint,"t":kind})
        row=self.session.execute(text("SELECT * FROM pk_pack_commands WHERE scope_key=:s AND command_key=:k FOR UPDATE"),{"s":scope,"k":key}).one()
        if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise PackAuthorityError("PK_COMMAND_CONFLICT")
        return row
    def _complete(self,scope,key,table,result_id):
        self.session.execute(text("UPDATE pk_pack_commands SET result_table=:t,result_id=:i,completed_at=now() WHERE scope_key=:s AND command_key=:k"),{"t":table,"i":result_id,"s":scope,"k":key})
    def _version_record(self,row):
        return PackVersionRecord(UUID(str(row.public_id)),row.pack_code,row.pack_version,row.owner_code,PackKind(row.pack_kind),row.manifest_sha256,row.retention_required)
    def _state(self,row):
        return TenantPackState(UUID(str(row.public_id)),row.tenant_id,row.pack_code,row.pack_version,PackStatus(row.lifecycle_status),row.row_version,row.retain_data)
    def register_version(self,command_key,fingerprint,m,canonical,manifest_hash):
        scope="platform";replay=self._command(scope,command_key,fingerprint,"register_pack_version")
        if replay.result_id:
            row=self.session.execute(text("""SELECT v.*,p.pack_code,p.owner_code,p.pack_kind FROM pk_pack_versions v JOIN pk_packs p ON p.id=v.pack_id WHERE v.id=:i"""),{"i":replay.result_id}).one();return self._version_record(row)
        pack=self.session.execute(text("SELECT * FROM pk_packs WHERE pack_code=:c FOR UPDATE"),{"c":m.pack_code}).first()
        if pack is None:
            pack=self.session.execute(text("INSERT INTO pk_packs(pack_code,owner_code,pack_kind) VALUES(:c,:o,:k) RETURNING *"),{"c":m.pack_code,"o":m.owner_code,"k":m.kind.value}).one()
        elif pack.owner_code!=m.owner_code or pack.pack_kind!=m.kind.value:raise PackAuthorityError("PK_PACK_IDENTITY_CONFLICT")
        existing=self.session.execute(text("SELECT * FROM pk_pack_versions WHERE pack_id=:p AND pack_version=:v FOR UPDATE"),{"p":pack.id,"v":m.version}).first()
        if existing:
            if existing.manifest_sha256!=manifest_hash:raise PackAuthorityError("PK_VERSION_IMMUTABILITY_CONFLICT")
            row=self.session.execute(text("SELECT v.*,p.pack_code,p.owner_code,p.pack_kind FROM pk_pack_versions v JOIN pk_packs p ON p.id=v.pack_id WHERE v.id=:i"),{"i":existing.id}).one();self._complete(scope,command_key,"pk_pack_versions",existing.id);return self._version_record(row)
        row=self.session.execute(text("""INSERT INTO pk_pack_versions(pack_id,pack_version,kernel_min,kernel_max,manifest_json,manifest_sha256,retention_required)
             VALUES(:p,:v,:min,:max,CAST(:manifest AS jsonb),:sha,:ret) RETURNING *"""),{"p":pack.id,"v":m.version,"min":m.kernel_min,"max":m.kernel_max,"manifest":canonical,"sha":manifest_hash,"ret":m.retention_required}).one()
        for d in m.dependencies:self.session.execute(text("INSERT INTO pk_pack_dependencies(pack_version_id,dependency_pack_code,version_spec,required) VALUES(:v,:c,:s,:r)"),{"v":row.id,"c":d.pack_code,"s":d.version_spec,"r":d.required})
        for e in m.extensions:self.session.execute(text("""INSERT INTO pk_pack_extensions(pack_version_id,extension_code,extension_kind,target_authority,public_interface,declaration_json)
             VALUES(:v,:c,:k,:a,:i,CAST(:d AS jsonb))"""),{"v":row.id,"c":e.extension_code,"k":e.kind.value,"a":e.target_authority,"i":e.public_interface,"d":json.dumps(_primitive(e.declaration),sort_keys=True)})
        for c in m.connectors:self.session.execute(text("""INSERT INTO pk_connector_declarations(pack_version_id,connector_code,connector_kind,provider_code,capabilities,provider_idempotency,external_reference_lookup,callback_identity_mode,finality_policy,destination_kinds,secret_reference_keys,ambiguous_outcome_policy,raw_payload_policy)
             VALUES(:v,:c,:k,:p,:caps,:idem,:lookup,:cb,CAST(:finality AS jsonb),:dest,:secret,:amb,:raw)"""),{"v":row.id,"c":c.connector_code,"k":c.kind.value,"p":c.provider_code,"caps":list(c.capabilities),"idem":c.provider_idempotency.value,"lookup":c.external_reference_lookup,"cb":c.callback_identity_mode,"finality":json.dumps({k:v.value for k,v in c.finality_policy.items()},sort_keys=True),"dest":list(c.destination_kinds),"secret":list(c.secret_reference_keys),"amb":c.ambiguous_outcome_policy,"raw":c.raw_payload_policy})
        self._complete(scope,command_key,"pk_pack_versions",row.id)
        joined=self.session.execute(text("SELECT v.*,p.pack_code,p.owner_code,p.pack_kind FROM pk_pack_versions v JOIN pk_packs p ON p.id=v.pack_id WHERE v.id=:i"),{"i":row.id}).one();return self._version_record(joined)
    def _installation(self,tenant,pack_code,lock=False):
        suffix=" FOR UPDATE" if lock else ""
        return self.session.execute(text("""SELECT i.*,p.pack_code,v.pack_version,v.retention_required FROM pk_tenant_pack_installations i JOIN pk_packs p ON p.id=i.pack_id JOIN pk_pack_versions v ON v.id=i.pack_version_id WHERE i.tenant_id=:t AND p.pack_code=:c"""+suffix),{"t":tenant,"c":pack_code}).first()
    def stage(self,c,fingerprint):
        scope=f"tenant:{c.tenant_id}";replay=self._command(scope,c.command_key,fingerprint,"stage_pack")
        if replay.result_id:return self._state(self.session.execute(text("""SELECT i.*,p.pack_code,v.pack_version FROM pk_tenant_pack_installations i JOIN pk_packs p ON p.id=i.pack_id JOIN pk_pack_versions v ON v.id=i.pack_version_id WHERE i.id=:i"""),{"i":replay.result_id}).one())
        version=self.session.execute(text("SELECT v.id,v.pack_id FROM pk_pack_versions v JOIN pk_packs p ON p.id=v.pack_id WHERE p.pack_code=:c AND v.pack_version=:v"),{"c":c.pack_code,"v":c.version}).first()
        if version is None:raise PackAuthorityError("PK_PACK_VERSION_NOT_FOUND")
        missing=self.session.execute(text("""SELECT d.dependency_pack_code FROM pk_pack_dependencies d WHERE d.pack_version_id=:v AND d.required=true AND NOT EXISTS(
             SELECT 1 FROM pk_tenant_pack_installations i JOIN pk_packs p ON p.id=i.pack_id JOIN pk_pack_versions pv ON pv.id=i.pack_version_id
             WHERE i.tenant_id=:t AND p.pack_code=d.dependency_pack_code AND i.lifecycle_status IN ('installed','active','disabled')) ORDER BY d.dependency_pack_code"""),{"v":version.id,"t":c.tenant_id}).scalars().all()
        if missing:raise PackAuthorityError("PK_DEPENDENCY_NOT_INSTALLED",",".join(missing))
        existing=self._installation(c.tenant_id,c.pack_code,True)
        if existing and existing.lifecycle_status!='removed':raise PackAuthorityError("PK_PACK_ALREADY_STAGED_OR_INSTALLED")
        if existing:
            row=self.session.execute(text("""UPDATE pk_tenant_pack_installations SET pack_version_id=:v,lifecycle_status='staged',row_version=row_version+1,staged_at=now(),installed_at=NULL,activated_at=NULL,disabled_at=NULL,removed_at=NULL,retain_data=true WHERE id=:i RETURNING *"""),{"v":version.id,"i":existing.id}).one()
            seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pk_pack_installation_history WHERE tenant_id=:t AND installation_id=:i"),{"t":c.tenant_id,"i":existing.id}).scalar_one()
        else:
            row=self.session.execute(text("INSERT INTO pk_tenant_pack_installations(tenant_id,pack_id,pack_version_id,lifecycle_status,staged_at) VALUES(:t,:p,:v,'staged',now()) RETURNING *"),{"t":c.tenant_id,"p":version.pack_id,"v":version.id}).one();seq=1
        self.session.execute(text("INSERT INTO pk_pack_installation_history(tenant_id,installation_id,sequence,from_status,to_status,pack_version_id,command_key,reason) VALUES(:t,:i,:s,NULL,'staged',:v,:k,'stage')"),{"t":c.tenant_id,"i":row.id,"s":seq,"v":version.id,"k":c.command_key})
        self._complete(scope,c.command_key,"pk_tenant_pack_installations",row.id);return self._state(self._installation(c.tenant_id,c.pack_code))
    def transition(self,c,fingerprint,allowed_from,to_status,reason):
        scope=f"tenant:{c.tenant_id}";kind=f"{to_status.value}_pack";replay=self._command(scope,c.command_key,fingerprint,kind)
        if replay.result_id:return self._state(self._installation(c.tenant_id,c.pack_code))
        row=self._installation(c.tenant_id,c.pack_code,True)
        if row is None:raise PackAuthorityError("PK_INSTALLATION_NOT_FOUND")
        allowed={allowed_from.value} if isinstance(allowed_from,PackStatus) else {x.value for x in allowed_from}
        if row.lifecycle_status not in allowed:raise PackAuthorityError("PK_INVALID_LIFECYCLE_TRANSITION")
        if row.row_version!=c.expected_row_version:raise PackAuthorityError("PK_CONCURRENT_CHANGE")
        if hasattr(c,'version') and row.pack_version!=c.version:raise PackAuthorityError("PK_VERSION_PIN_MISMATCH")
        if to_status is PackStatus.INSTALLED:
            missing=self.session.execute(text("""SELECT d.dependency_pack_code FROM pk_pack_dependencies d WHERE d.pack_version_id=:v AND d.required=true AND NOT EXISTS(
             SELECT 1 FROM pk_tenant_pack_installations i JOIN pk_packs p ON p.id=i.pack_id WHERE i.tenant_id=:t AND p.pack_code=d.dependency_pack_code AND i.lifecycle_status IN ('installed','active','disabled'))"""),{"v":row.pack_version_id,"t":c.tenant_id}).scalars().all()
            if missing:raise PackAuthorityError("PK_DEPENDENCY_NOT_INSTALLED",",".join(sorted(missing)))
        stamp={PackStatus.INSTALLED:'installed_at',PackStatus.ACTIVE:'activated_at',PackStatus.DISABLED:'disabled_at'}[to_status]
        updated=self.session.execute(text(f"UPDATE pk_tenant_pack_installations SET lifecycle_status=:to,row_version=row_version+1,{stamp}=now() WHERE id=:i RETURNING *"),{"to":to_status.value,"i":row.id}).one()
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pk_pack_installation_history WHERE tenant_id=:t AND installation_id=:i"),{"t":c.tenant_id,"i":row.id}).scalar_one()
        self.session.execute(text("INSERT INTO pk_pack_installation_history(tenant_id,installation_id,sequence,from_status,to_status,pack_version_id,command_key,reason) VALUES(:t,:i,:s,:f,:to,:v,:k,:r)"),{"t":c.tenant_id,"i":row.id,"s":seq,"f":row.lifecycle_status,"to":to_status.value,"v":row.pack_version_id,"k":c.command_key,"r":reason})
        self._complete(scope,c.command_key,"pk_tenant_pack_installations",row.id);return self._state(self._installation(c.tenant_id,c.pack_code))
    def remove(self,c,fingerprint):
        scope=f"tenant:{c.tenant_id}";replay=self._command(scope,c.command_key,fingerprint,"remove_pack")
        if replay.result_id:return self._state(self._installation(c.tenant_id,c.pack_code))
        row=self._installation(c.tenant_id,c.pack_code,True)
        if row is None:raise PackAuthorityError("PK_INSTALLATION_NOT_FOUND")
        if row.lifecycle_status!='disabled':raise PackAuthorityError("PK_INVALID_LIFECYCLE_TRANSITION")
        if row.row_version!=c.expected_row_version:raise PackAuthorityError("PK_CONCURRENT_CHANGE")
        if row.retention_required and not c.retain_data:raise PackAuthorityError("PK_RETENTION_REQUIRED")
        dependents=self.session.execute(text("""SELECT p2.pack_code FROM pk_tenant_pack_installations i2 JOIN pk_packs p2 ON p2.id=i2.pack_id JOIN pk_pack_dependencies d ON d.pack_version_id=i2.pack_version_id WHERE i2.tenant_id=:t AND i2.lifecycle_status IN ('installed','active','disabled') AND d.required=true AND d.dependency_pack_code=:c"""),{"t":c.tenant_id,"c":c.pack_code}).scalars().all()
        if dependents:raise PackAuthorityError("PK_REQUIRED_BY_INSTALLED_PACK",",".join(sorted(dependents)))
        updated=self.session.execute(text("UPDATE pk_tenant_pack_installations SET lifecycle_status='removed',row_version=row_version+1,removed_at=now(),retain_data=:retain WHERE id=:i RETURNING *"),{"retain":c.retain_data,"i":row.id}).one()
        seq=self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pk_pack_installation_history WHERE tenant_id=:t AND installation_id=:i"),{"t":c.tenant_id,"i":row.id}).scalar_one()
        self.session.execute(text("INSERT INTO pk_pack_installation_history(tenant_id,installation_id,sequence,from_status,to_status,pack_version_id,command_key,reason) VALUES(:t,:i,:s,:f,'removed',:v,:k,:r)"),{"t":c.tenant_id,"i":row.id,"s":seq,"f":row.lifecycle_status,"v":row.pack_version_id,"k":c.command_key,"r":c.reason})
        self._complete(scope,c.command_key,"pk_tenant_pack_installations",row.id);return self._state(self._installation(c.tenant_id,c.pack_code))
    def state(self,tenant_id,pack_code):
        row=self._installation(tenant_id,pack_code);return None if row is None else self._state(row)
    def history(self,tenant_id,pack_code):
        row=self._installation(tenant_id,pack_code)
        if row is None:return []
        rows=self.session.execute(text("""SELECT h.*,v.pack_version FROM pk_pack_installation_history h JOIN pk_pack_versions v ON v.id=h.pack_version_id WHERE h.tenant_id=:t AND h.installation_id=:i ORDER BY h.sequence"""),{"t":tenant_id,"i":row.id}).all()
        return [PackHistoryEvent(r.sequence,PackStatus(r.from_status) if r.from_status else None,PackStatus(r.to_status),r.pack_version,r.command_key,r.occurred_at,r.reason) for r in rows]
