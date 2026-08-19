from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from pack_platform import PackAuthority, PackKind, PackVersionRecord
from pack_platform.pk456_contracts import ConformanceResult, PackCertificationRecord
from pack_platform.pk456_service import PK456Authority
from restaurant.r4 import (
    PACK_CODE, PACK_VERSION, RestaurantPackRegistration, build_registration_plan,
    build_restaurant_pack_manifest, plan_fingerprint,
)

EVIDENCE=("a"*64,"b"*64,"c"*64)


class RegisterRepo:
    def __init__(self): self.calls=[]
    def register_version(self,key,fingerprint,m,canonical,h):
        self.calls.append((key,fingerprint,m,canonical,h))
        return PackVersionRecord(UUID(int=1),m.pack_code,m.version,m.owner_code,m.kind,h,m.retention_required)


class CertRepo:
    def __init__(self,manifest_sha): self.manifest_sha=manifest_sha; self.calls=[]
    def pack_version(self,code,version): return {"manifest_sha256":self.manifest_sha} if (code,version)==(PACK_CODE,PACK_VERSION) else None
    def certify(self,*args):
        self.calls.append(args)
        return PackCertificationRecord(UUID(int=2),PACK_CODE,PACK_VERSION,"restaurant.r4.conformance","1.0.0",self.manifest_sha,args[7],ConformanceResult.PASS)


def test_manifest_is_pk_industry_pack_and_composes_existing_authorities():
    m=build_restaurant_pack_manifest()
    assert (m.pack_code,m.version,m.owner_code,m.kind)==("industry.restaurant","1.0.0","restaurant",PackKind.INDUSTRY)
    assert {"catalog","finance","inventory","party","resources","semantics","operating_context","security_authority"}.issubset(set(m.required_modules))
    assert {"communications","documents","reports","scheduling"}.issubset(set(m.optional_modules))


def test_manifest_does_not_make_tables_wnd_or_connectors_universal():
    m=build_restaurant_pack_manifest()
    assert m.connectors==() and m.xa["tables_required"] is False and m.xa["wnd_profile_is_standard"] is False
    assert m.xa["frontend_implemented"] is False and m.xa["composition_engine_implemented"] is False


def test_semantics_are_pack_scoped_open_contributions_via_pc3():
    plan=build_registration_plan(EVIDENCE)
    s=plan.semantic_contribution
    assert s.namespace_code=="restaurant" and s.scope=="pack" and s.closed_value_sets is False
    assert "restaurant.service_mode" in s.taxonomy_systems
    ext=next(e for e in plan.manifest.extensions if e.extension_code=="restaurant.semantics")
    assert ext.target_authority=="PC3" and ext.public_interface=="core.platform.semantics.SemanticAuthority"


def test_configuration_has_no_industry_wide_wnd_defaults():
    plan=build_registration_plan(EVIDENCE)
    assert plan.configuration and all(x.owner=="PC4" and x.default_policy=="template_or_tenant_required" for x in plan.configuration)
    assert any(x.key=="restaurant.tables.enabled" for x in plan.configuration)


def test_registration_uses_real_pk_public_authority_contract():
    repo=RegisterRepo();a=PackAuthority(repo)
    record=RestaurantPackRegistration.register(a)
    assert record.pack_code==PACK_CODE and record.version==PACK_VERSION and len(record.manifest_sha256)==64
    assert len(repo.calls)==1


def test_certification_covers_all_pk456_checks_and_real_authority_contract():
    rrepo=RegisterRepo();record=RestaurantPackRegistration.register(PackAuthority(rrepo))
    repo=CertRepo(record.manifest_sha256);cert=RestaurantPackRegistration.certify(PK456Authority(repo),EVIDENCE)
    assert cert.result is ConformanceResult.PASS
    command=build_registration_plan(EVIDENCE).certification_command
    assert set(command.evidence.checks)=={"architecture","tenant_isolation","migration_compatibility","authorization","semantics","finance","shared_operations","xa","manifest"}
    assert set(command.evidence.evidence_sha256)==set(EVIDENCE)


def test_r4_authorizes_no_tenant_install_template_or_wnd_cutover():
    plan=build_registration_plan(EVIDENCE)
    assert plan.tenant_installation_authorized is False
    assert plan.template_application_authorized is False
    assert plan.wnd_cutover_authorized is False


def test_manifest_finance_is_reference_only_and_has_no_provider_connector():
    m=build_restaurant_pack_manifest()
    f=next(e for e in m.extensions if e.extension_code=="restaurant.finance_conformance")
    assert f.target_authority=="Neutral Finance" and f.declaration["restaurant_finance_writer"] is False
    assert m.finance_conformance_profile=="restaurant.r3.financial_semantics.v1"


def test_plan_fingerprint_is_deterministic():
    assert plan_fingerprint()==plan_fingerprint(build_restaurant_pack_manifest())
    assert len(plan_fingerprint())==64


def test_r4_source_has_no_direct_persistence_or_private_authority_imports():
    root=Path(__file__).resolve().parents[2]
    source=(root/'restaurant/r4/service.py').read_text(encoding='utf-8').lower()
    for token in ('sql_repository','from database import','session.execute','insert into','update pk_','delete from'):
        assert token not in source


def test_r4_has_no_schema_migration_or_r4_tables():
    root=Path(__file__).resolve().parents[2]
    assert not list((root/'alembic_neutral/versions').glob('r4_*'))
    assert not list((root/'alembic_neutral/sql').glob('r4_*'))


def test_r4_source_checkpoint_and_r5_readiness_contract():
    import json
    root=Path(__file__).resolve().parents[2]
    a=json.loads((root/'contracts/restaurant/v1/r4_pack_registration_authority.json').read_text())
    ready=json.loads((root/'contracts/restaurant/v1/r4_r5_readiness.json').read_text())
    assert a['source_checkpoint']=='64fa78ef9df34a263ebfff449839bbeca477aac7'
    assert a['accepted_head']=='r2_restaurant_menu_fulfillment_043' and a['migration']=='NONE'
    assert ready['status']=='READY_WHEN_R4_SINGLE_GATE_PASS'
