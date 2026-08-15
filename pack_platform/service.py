"""PK0-PK3 pack authority: validation, idempotent lifecycle and extension boundaries."""
from __future__ import annotations
import hashlib, json, re
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any
from .contracts import *

_TOKEN=re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_VERSION=re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9.-]+)?$")
_FORBIDDEN_INTERFACE=("sql_repository","private","table:","insert ","update ","delete ","select ","drop ","alter ")
_SECRET_KEYS={"password","api_key","access_token","secret_value","private_key","client_secret","credential"}

class PackAuthorityError(RuntimeError):
    def __init__(self,code:str,detail:str|None=None):
        self.code=code;self.detail=detail
        super().__init__(code if detail is None else f"{code}: {detail}")

def _token(value:str,field:str)->str:
    value=str(value).strip().lower()
    if not _TOKEN.fullmatch(value):raise PackAuthorityError("PK_INVALID_TOKEN",field)
    return value

def _version(value:str)->str:
    value=str(value).strip()
    if not _VERSION.fullmatch(value):raise PackAuthorityError("PK_INVALID_VERSION",value)
    return value

def _primitive(value):
    if isinstance(value,Enum):return value.value
    if is_dataclass(value):return {k:_primitive(v) for k,v in asdict(value).items()}
    if isinstance(value,dict):return {str(k):_primitive(v) for k,v in sorted(value.items(),key=lambda item:str(item[0]))}
    if isinstance(value,(tuple,list)):return [_primitive(v) for v in value]
    return value

def _canonical(value)->str:return json.dumps(_primitive(value),sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _fingerprint(kind:str,payload)->str:return hashlib.sha256((kind+"\0"+_canonical(payload)).encode()).hexdigest()

def _scan_secret_material(value:Any,path:str="manifest"):
    if isinstance(value,dict):
        for key,item in value.items():
            low=str(key).lower()
            if low in _SECRET_KEYS or low.endswith("_password") or low.endswith("_secret"):
                raise PackAuthorityError("PK_SECRET_MATERIAL_FORBIDDEN",f"{path}.{key}")
            _scan_secret_material(item,f"{path}.{key}")
    elif isinstance(value,(list,tuple)):
        for idx,item in enumerate(value):_scan_secret_material(item,f"{path}[{idx}]")

class PackAuthority:
    def __init__(self,repository,public_interface_resolver=None):
        self.repository=repository
        self.public_interface_resolver=public_interface_resolver

    def _validate_manifest(self,m:PackManifest)->PackManifest:
        code=_token(m.pack_code,"pack_code");owner=_token(m.owner_code,"owner_code");version=_version(m.version);kernel_min=_version(m.kernel_min);kernel_max=_version(m.kernel_max) if m.kernel_max else None
        required=tuple(sorted({_token(x,"required_module") for x in m.required_modules}))
        optional=tuple(sorted({_token(x,"optional_module") for x in m.optional_modules}))
        if set(required)&set(optional):raise PackAuthorityError("PK_MODULE_DECLARATION_CONFLICT")
        deps=[];seen=set()
        for d in m.dependencies:
            dep=_token(d.pack_code,"dependency_pack")
            if dep==code:raise PackAuthorityError("PK_SELF_DEPENDENCY")
            if dep in seen:raise PackAuthorityError("PK_DUPLICATE_DEPENDENCY",dep)
            seen.add(dep);deps.append(PackDependency(dep,str(d.version_spec).strip(),bool(d.required)))
        exts=[];seen_ext=set()
        for e in m.extensions:
            ec=_token(e.extension_code,"extension_code")
            if ec in seen_ext:raise PackAuthorityError("PK_DUPLICATE_EXTENSION",ec)
            seen_ext.add(ec);authority=str(e.target_authority).strip();interface=str(e.public_interface).strip()
            low=interface.lower()
            if not authority or not interface or any(x in low for x in _FORBIDDEN_INTERFACE):raise PackAuthorityError("PK_PRIVATE_EXTENSION_FORBIDDEN",ec)
            if self.public_interface_resolver is not None and not self.public_interface_resolver(authority,interface):raise PackAuthorityError("PK_UNKNOWN_PUBLIC_INTERFACE",ec)
            _scan_secret_material(e.declaration,f"extension.{ec}")
            exts.append(PackExtension(ec,e.kind,authority,interface,dict(e.declaration)))
        connectors=[];seen_connector=set()
        for c in m.connectors:
            cc=_token(c.connector_code,"connector_code");provider=_token(c.provider_code,"provider_code")
            if cc in seen_connector:raise PackAuthorityError("PK_DUPLICATE_CONNECTOR",cc)
            seen_connector.add(cc)
            capabilities=tuple(sorted({_token(x,"connector_capability") for x in c.capabilities}))
            finality={str(k).strip():ExecutionState(v) for k,v in c.finality_policy.items()}
            states=set(finality.values())
            if c.kind is ConnectorKind.PAYMENT_PROVIDER and "payout" in capabilities:
                required_states={ExecutionState.SUBMITTED,ExecutionState.PENDING,ExecutionState.FAILED,ExecutionState.AMBIGUOUS,ExecutionState.PROVIDER_FINAL}
                if not required_states.issubset(states):raise PackAuthorityError("PK_PAYOUT_FINALITY_INCOMPLETE",cc)
                if c.provider_idempotency is ProviderIdempotency.UNSUPPORTED and not c.external_reference_lookup and c.ambiguous_outcome_policy!="manual_hold_no_blind_retry":raise PackAuthorityError("PK_UNSAFE_PAYOUT_RETRY_POLICY",cc)
            for ref in c.secret_reference_keys:_token(ref,"secret_reference_key")
            if c.raw_payload_policy not in {"sanitized_only","sanitized_or_encrypted_only","encrypted_reference_only","forbidden"}:raise PackAuthorityError("PK_RAW_PAYLOAD_POLICY",cc)
            connectors.append(ConnectorDeclaration(cc,c.kind,provider,capabilities,c.provider_idempotency,bool(c.external_reference_lookup),_token(c.callback_identity_mode,"callback_identity_mode"),finality,tuple(sorted({_token(x,"destination_kind") for x in c.destination_kinds})),tuple(sorted({_token(x,"secret_reference_key") for x in c.secret_reference_keys})),c.ambiguous_outcome_policy,c.raw_payload_policy))
        xa=dict(m.xa);_scan_secret_material(xa,"xa")
        return PackManifest(code,version,owner,m.kind,kernel_min,kernel_max,required,optional,tuple(deps),tuple(sorted({_token(x,"permission_reference") for x in m.permission_references})),tuple(sorted({_token(x,"semantic_namespace") for x in m.semantic_namespaces})),tuple(sorted({_token(x,"configuration_key") for x in m.configuration_keys})),tuple(exts),tuple(connectors),xa,m.finance_conformance_profile,bool(m.retention_required))

    def register(self,command:RegisterPackVersion)->PackVersionRecord:
        manifest=self._validate_manifest(command.manifest)
        payload={"manifest":manifest}
        canonical=_canonical(manifest);manifest_hash=hashlib.sha256(canonical.encode()).hexdigest()
        return self.repository.register_version(command.command_key,_fingerprint("register_pack_version",payload),manifest,canonical,manifest_hash)

    def stage(self,command:StagePack)->TenantPackState:
        normalized=StagePack(command.command_key,int(command.tenant_id),_token(command.pack_code,"pack_code"),_version(command.version))
        return self.repository.stage(normalized,_fingerprint("stage_pack",normalized))
    def install(self,command:InstallPack)->TenantPackState:
        normalized=InstallPack(command.command_key,int(command.tenant_id),_token(command.pack_code,"pack_code"),_version(command.version),int(command.expected_row_version))
        return self.repository.transition(normalized,_fingerprint("install_pack",normalized),PackStatus.STAGED,PackStatus.INSTALLED,None)
    def activate(self,command:ActivatePack)->TenantPackState:
        normalized=ActivatePack(command.command_key,int(command.tenant_id),_token(command.pack_code,"pack_code"),_version(command.version),int(command.expected_row_version))
        return self.repository.transition(normalized,_fingerprint("activate_pack",normalized),(PackStatus.INSTALLED,PackStatus.DISABLED),PackStatus.ACTIVE,None)
    def disable(self,command:DisablePack)->TenantPackState:
        normalized=DisablePack(command.command_key,int(command.tenant_id),_token(command.pack_code,"pack_code"),int(command.expected_row_version),str(command.reason).strip())
        if not normalized.reason:raise PackAuthorityError("PK_REASON_REQUIRED")
        return self.repository.transition(normalized,_fingerprint("disable_pack",normalized),PackStatus.ACTIVE,PackStatus.DISABLED,normalized.reason)
    def remove(self,command:RemovePack)->TenantPackState:
        normalized=RemovePack(command.command_key,int(command.tenant_id),_token(command.pack_code,"pack_code"),int(command.expected_row_version),bool(command.retain_data),str(command.reason).strip())
        if not normalized.reason:raise PackAuthorityError("PK_REASON_REQUIRED")
        return self.repository.remove(normalized,_fingerprint("remove_pack",normalized))
