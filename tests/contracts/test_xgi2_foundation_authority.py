from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.platform.structure.contracts import (
    LegalEntity,
    Location,
    LocationKind,
    OrganizationUnit,
    StructuralContext,
    Tenant,
    TenantLifecycle,
)
from core.platform.structure.currency_foundation_contract import (
    CurrencyAsset,
    RegisterCurrencyAsset,
    SetTenantCurrencyPolicy,
    TenantCurrencyPolicy,
)
from core.platform.structure.currency_foundation_service import (
    CurrencyFoundationAuthority,
)
from core.platform.structure.identity_import_contract import ImportTenantIdentity
from core.platform.structure.identity_import_service import (
    TenantIdentityImportAuthority,
)
from core.platform.structure.service import StructuralAuthorityError

ROOT = Path(__file__).resolve().parents[2]


def wnd_import() -> ImportTenantIdentity:
    return ImportTenantIdentity(
        command_key="pc1:tenant-identity-import:2:wnd:v1",
        tenant_id=2,
        tenant_code="wnd",
        tenant_name="Wine & Dine",
        country_code="CM",
        currency="XAF",
        locale="fr-CM",
        timezone="Africa/Douala",
        legal_entity_code="WND-CM",
        legal_entity_name="Wine & Dine Cameroon",
        root_organization_code="WND",
        root_organization_name="Wine & Dine",
        primary_location_code="LOGPOM",
        primary_location_name="Logpom",
    )


def context() -> StructuralContext:
    return StructuralContext(
        Tenant(
            2,
            "wnd",
            "Wine & Dine",
            TenantLifecycle.ACTIVE,
            "CM",
            "XAF",
            "fr-CM",
            "Africa/Douala",
        ),
        OrganizationUnit(20, __import__("uuid").UUID(int=20), 2, "WND", "Wine & Dine", "root"),
        LegalEntity(
            30,
            __import__("uuid").UUID(int=30),
            2,
            "WND-CM",
            "Wine & Dine Cameroon",
            "CM",
        ),
        Location(
            40,
            __import__("uuid").UUID(int=40),
            2,
            "LOGPOM",
            "Logpom",
            LocationKind.PHYSICAL,
            30,
            "Africa/Douala",
        ),
        (20,),
    )


class IdentityMemoryRepo:
    def __init__(self):
        self.calls = []
        self.value = context()

    def import_tenant(self, command, request_fingerprint):
        self.calls.append((command, request_fingerprint))
        return self.value


class CurrencyMemoryRepo:
    def __init__(self):
        self.asset_calls = []
        self.policy_calls = []

    def register_asset(self, command, request_fingerprint):
        self.asset_calls.append((command, request_fingerprint))
        return CurrencyAsset(
            command.code,
            command.asset_kind,
            command.display_name,
            command.minor_unit_scale,
            command.maximum_storage_scale,
            command.active,
        )

    def set_tenant_policy(self, command, request_fingerprint):
        self.policy_calls.append((command, request_fingerprint))
        return TenantCurrencyPolicy(
            command.tenant_id,
            command.currency_code,
            command.rounding_mode,
            Decimal(command.cash_rounding_increment),
            command.active,
            command.effective_from,
            command.effective_to,
            command.policy_version,
        )


def xaf_asset() -> RegisterCurrencyAsset:
    return RegisterCurrencyAsset(
        command_key="pc1:currency-asset:XAF:v1",
        code="XAF",
        asset_kind="fiat",
        display_name="Central African CFA franc",
        minor_unit_scale=0,
        maximum_storage_scale=8,
    )


def xaf_policy() -> SetTenantCurrencyPolicy:
    return SetTenantCurrencyPolicy(
        command_key="pc1:tenant-currency-policy:2:XAF:1",
        tenant_id=2,
        currency_code="XAF",
        rounding_mode="half_even",
        cash_rounding_increment=Decimal(0),
        active=True,
        effective_from=datetime(2026, 9, 19, tzinfo=timezone.utc),
        policy_version=1,
    )


def test_tenant_identity_import_uses_exact_wnd_profile_and_existing_pc1_contract():
    command = wnd_import()
    provision = command.as_provision_tenant()
    assert command.tenant_id == 2
    assert (
        provision.tenant_code,
        provision.tenant_name,
        provision.country_code,
        provision.currency,
        provision.locale,
        provision.timezone,
    ) == ("wnd", "Wine & Dine", "CM", "XAF", "fr-CM", "Africa/Douala")
    assert (provision.legal_entity_code, provision.legal_entity_name) == (
        "WND-CM",
        "Wine & Dine Cameroon",
    )
    assert (provision.root_organization_code, provision.primary_location_code) == (
        "WND",
        "LOGPOM",
    )


def test_identity_import_fingerprint_is_deterministic_and_payload_sensitive():
    repo = IdentityMemoryRepo()
    authority = TenantIdentityImportAuthority(repo)
    first = wnd_import()
    assert authority.import_tenant(first) == context()
    fp = repo.calls[-1][1]
    assert authority.import_tenant(first) == context()
    assert repo.calls[-1][1] == fp
    authority.import_tenant(replace(first, tenant_name="Different"))
    assert repo.calls[-1][1] != fp


def test_identity_import_rejects_invalid_identity_before_repository_call():
    repo = IdentityMemoryRepo()
    with pytest.raises(StructuralAuthorityError, match="invalid_tenant_identity_import"):
        TenantIdentityImportAuthority(repo).import_tenant(replace(wnd_import(), tenant_id=0))
    assert repo.calls == []


def test_identity_repository_freezes_collision_and_sequence_safety_laws():
    source = (
        ROOT / "core/platform/structure/identity_import_repository.py"
    ).read_text(encoding="utf-8")
    assert "LOCK TABLE public.tenants IN SHARE ROW EXCLUSIVE MODE" in source
    assert "tenant_id_collision" in source
    assert "tenant_code_collision" in source
    assert "unowned_existing_tenant_identity" in source
    assert "conflicting_tenant_identity_import_replay" in source
    assert "pg_get_serial_sequence('public.tenants','id')" in source
    assert "pg_sequence_last_value" in source
    assert "setval(CAST(:seq AS regclass),:target,true)" in source


def test_xaf_asset_contract_is_exact_and_generic():
    command = xaf_asset()
    assert command.canonical_payload()["code"] == "XAF"
    assert command.asset_kind == "fiat"
    assert command.minor_unit_scale == 0
    assert command.maximum_storage_scale == 8
    assert command.source_component == "pc1.currency_foundation"


def test_currency_authority_fingerprints_are_deterministic():
    repo = CurrencyMemoryRepo()
    authority = CurrencyFoundationAuthority(repo)
    authority.register_asset(xaf_asset())
    first = repo.asset_calls[-1][1]
    authority.register_asset(xaf_asset())
    assert repo.asset_calls[-1][1] == first

    authority.set_tenant_policy(xaf_policy())
    policy_fp = repo.policy_calls[-1][1]
    authority.set_tenant_policy(xaf_policy())
    assert repo.policy_calls[-1][1] == policy_fp


def test_tenant_xaf_policy_is_exact_and_aware():
    command = xaf_policy()
    assert command.tenant_id == 2
    assert command.currency_code == "XAF"
    assert command.rounding_mode == "half_even"
    assert command.cash_rounding_increment == 0
    assert command.policy_version == 1
    assert command.effective_from.isoformat() == "2026-09-19T00:00:00+00:00"

    repo = CurrencyMemoryRepo()
    with pytest.raises(StructuralAuthorityError, match="currency_policy_timestamp_not_aware"):
        CurrencyFoundationAuthority(repo).set_tenant_policy(
            replace(
                command,
                effective_from=datetime(2026, 9, 19, tzinfo=timezone.utc).replace(
                    tzinfo=None
                ),
            )
        )


def test_currency_repository_freezes_replay_conflict_and_overlap_laws():
    source = (
        ROOT / "core/platform/structure/currency_foundation_repository.py"
    ).read_text(encoding="utf-8")
    assert "currency_asset_conflict" in source
    assert "tenant_currency_policy_conflict" in source
    assert "tenant_currency_policy_overlap" in source
    assert "kernel_source_records" in source
    assert "request_fingerprint" in source
    assert "COALESCE(effective_to,'infinity'::timestamptz)" in source


def test_r4d_does_not_modify_historical_pc1_or_finance_kernel_sources():
    prohibited = {
        "core/platform/structure/contracts.py",
        "core/platform/structure/service.py",
        "core/platform/structure/sql_repository.py",
    }
    status = __import__("subprocess").check_output(
        ["git", "status", "--porcelain=v1", "-uall"],
        cwd=ROOT,
        text=True,
    )
    changed = {line[3:].replace("\\", "/") for line in status.splitlines() if line}
    assert not (changed & prohibited)
    assert not any(path.startswith("core/domain/finance/") for path in changed)
    assert not any(path.startswith("alembic_neutral/") for path in changed)


def test_r4d_authority_declares_exact_eleven_path_envelope():
    import json

    contract = json.loads(
        (ROOT / "contracts/platform/v1/xgi2_foundation_authority.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["authority"] == "XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION"
    assert len(contract["authorized_paths"]) == 11
    assert contract["database_foundation_rows"] is False
    assert contract["schema_mutation"] is False
