from __future__ import annotations
from dataclasses import replace
from pack_platform import *
from pack_platform.service import PackAuthorityError

class FakeRepo:
    def __init__(self):self.registered=[]
    def register_version(self,key,fingerprint,m,canonical,h):self.registered.append((m,h));return PackVersionRecord(__import__('uuid').uuid4(),m.pack_code,m.version,m.owner_code,m.kind,h,m.retention_required)

def payout(**overrides):
    base=dict(connector_code="payout.example",kind=ConnectorKind.PAYMENT_PROVIDER,provider_code="example",capabilities=("payout",),provider_idempotency=ProviderIdempotency.EXTERNAL_REFERENCE,external_reference_lookup=True,callback_identity_mode="provider_event_id",finality_policy={"accepted":ExecutionState.SUBMITTED,"processing":ExecutionState.PENDING,"failed":ExecutionState.FAILED,"timeout":ExecutionState.AMBIGUOUS,"credited":ExecutionState.PROVIDER_FINAL},destination_kinds=("provider_beneficiary_token",),secret_reference_keys=("example.credentials",))
    base.update(overrides);return ConnectorDeclaration(**base)

def manifest(**overrides):
    base=dict(pack_code="neutral.payments",version="1.0.0",owner_code="pk",kind=PackKind.CAPABILITY,kernel_min="1.0.0",required_modules=("finance",),extensions=(PackExtension("finance.conformance",ExtensionKind.FINANCE_CONFORMANCE,"Neutral Finance","core.domain.finance.pack_conformance_service",{}),),connectors=(payout(),))
    base.update(overrides);return PackManifest(**base)

def test_manifest_is_immutable_typed_composition_contract():
    repo=FakeRepo();a=PackAuthority(repo);r=a.register(RegisterPackVersion("r1",manifest()))
    assert r.pack_code=="neutral.payments" and len(r.manifest_sha256)==64
    assert repo.registered[0][0].connectors[0].finality_policy["credited"] is ExecutionState.PROVIDER_FINAL

def test_pack_cannot_bind_private_interface_or_secret_material():
    a=PackAuthority(FakeRepo())
    bad=manifest(extensions=(PackExtension("bad",ExtensionKind.REPORT,"SO9","shared_operations.so9.sql_repository",{}),))
    try:a.register(RegisterPackVersion("r",bad));assert False
    except PackAuthorityError as e:assert e.code=="PK_PRIVATE_EXTENSION_FORBIDDEN"
    bad2=manifest(xa={"api_key":"secret"})
    try:a.register(RegisterPackVersion("r2",bad2));assert False
    except PackAuthorityError as e:assert e.code=="PK_SECRET_MATERIAL_FORBIDDEN"

def test_payout_connector_requires_explicit_finality_and_safe_ambiguity():
    a=PackAuthority(FakeRepo())
    incomplete=payout(finality_policy={"credited":ExecutionState.PROVIDER_FINAL})
    try:a.register(RegisterPackVersion("r",manifest(connectors=(incomplete,))));assert False
    except PackAuthorityError as e:assert e.code=="PK_PAYOUT_FINALITY_INCOMPLETE"
    unsafe=payout(provider_idempotency=ProviderIdempotency.UNSUPPORTED,external_reference_lookup=False,ambiguous_outcome_policy="retry")
    try:a.register(RegisterPackVersion("r2",manifest(connectors=(unsafe,))));assert False
    except PackAuthorityError as e:assert e.code=="PK_UNSAFE_PAYOUT_RETRY_POLICY"

def test_manifest_cannot_duplicate_module_or_dependency_identity():
    a=PackAuthority(FakeRepo())
    try:a.register(RegisterPackVersion("r",manifest(required_modules=("finance",),optional_modules=("finance",))));assert False
    except PackAuthorityError as e:assert e.code=="PK_MODULE_DECLARATION_CONFLICT"
    try:a.register(RegisterPackVersion("r2",manifest(dependencies=(PackDependency("neutral.payments","1"),))));assert False
    except PackAuthorityError as e:assert e.code=="PK_SELF_DEPENDENCY"
