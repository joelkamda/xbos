"""PK0-PK3 pack manifest, lifecycle, extension and connector contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class PackKind(StrEnum):
    CAPABILITY="capability"
    INDUSTRY="industry"
    COUNTRY="country"
    TAX="tax"
    PAYMENT_CONNECTOR="payment_connector"
    COMMUNICATION_CONNECTOR="communication_connector"
    ACCOUNTING_CONNECTOR="accounting_connector"
    INTEGRATION_CONNECTOR="integration_connector"

class PackStatus(StrEnum):
    STAGED="staged"
    INSTALLED="installed"
    ACTIVE="active"
    DISABLED="disabled"
    REMOVED="removed"

class ExtensionKind(StrEnum):
    CONFIGURATION="configuration"
    SEMANTICS="semantics"
    NAVIGATION="navigation"
    WORKFLOW="workflow"
    DOCUMENT="document"
    REPORT="report"
    CONNECTOR="connector"
    FINANCE_CONFORMANCE="finance_conformance"
    LOCALIZATION="localization"

class ConnectorKind(StrEnum):
    PAYMENT_PROVIDER="payment_provider"
    COMMUNICATION_PROVIDER="communication_provider"
    ACCOUNTING_PROVIDER="accounting_provider"
    EXTERNAL_SYSTEM="external_system"

class ProviderIdempotency(StrEnum):
    NATIVE="native"
    EXTERNAL_REFERENCE="external_reference"
    UNSUPPORTED="unsupported"

class ExecutionState(StrEnum):
    SUBMITTED="submitted"
    PENDING="pending"
    FAILED="failed"
    AMBIGUOUS="ambiguous"
    PROVIDER_FINAL="provider_final"

@dataclass(frozen=True)
class PackDependency:
    pack_code:str
    version_spec:str
    required:bool=True

@dataclass(frozen=True)
class PackExtension:
    extension_code:str
    kind:ExtensionKind
    target_authority:str
    public_interface:str
    declaration:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class ConnectorDeclaration:
    connector_code:str
    kind:ConnectorKind
    provider_code:str
    capabilities:tuple[str,...]
    provider_idempotency:ProviderIdempotency
    external_reference_lookup:bool
    callback_identity_mode:str
    finality_policy:dict[str,ExecutionState]
    destination_kinds:tuple[str,...]=()
    secret_reference_keys:tuple[str,...]=()
    ambiguous_outcome_policy:str="manual_hold_no_blind_retry"
    raw_payload_policy:str="sanitized_or_encrypted_only"

@dataclass(frozen=True)
class PackManifest:
    pack_code:str
    version:str
    owner_code:str
    kind:PackKind
    kernel_min:str
    kernel_max:str|None=None
    required_modules:tuple[str,...]=()
    optional_modules:tuple[str,...]=()
    dependencies:tuple[PackDependency,...]=()
    permission_references:tuple[str,...]=()
    semantic_namespaces:tuple[str,...]=()
    configuration_keys:tuple[str,...]=()
    extensions:tuple[PackExtension,...]=()
    connectors:tuple[ConnectorDeclaration,...]=()
    xa:dict[str,Any]=field(default_factory=dict)
    finance_conformance_profile:str|None=None
    retention_required:bool=True

@dataclass(frozen=True)
class RegisterPackVersion:
    command_key:str
    manifest:PackManifest

@dataclass(frozen=True)
class StagePack:
    command_key:str; tenant_id:int; pack_code:str; version:str
@dataclass(frozen=True)
class InstallPack:
    command_key:str; tenant_id:int; pack_code:str; version:str; expected_row_version:int
@dataclass(frozen=True)
class ActivatePack:
    command_key:str; tenant_id:int; pack_code:str; version:str; expected_row_version:int
@dataclass(frozen=True)
class DisablePack:
    command_key:str; tenant_id:int; pack_code:str; expected_row_version:int; reason:str
@dataclass(frozen=True)
class RemovePack:
    command_key:str; tenant_id:int; pack_code:str; expected_row_version:int; retain_data:bool; reason:str

@dataclass(frozen=True)
class PackVersionRecord:
    public_id:UUID; pack_code:str; version:str; owner_code:str; kind:PackKind; manifest_sha256:str; retention_required:bool
@dataclass(frozen=True)
class TenantPackState:
    public_id:UUID; tenant_id:int; pack_code:str; version:str; status:PackStatus; row_version:int; retain_data:bool
@dataclass(frozen=True)
class PackHistoryEvent:
    sequence:int; from_status:PackStatus|None; to_status:PackStatus; version:str; command_key:str; occurred_at:datetime; reason:str|None
