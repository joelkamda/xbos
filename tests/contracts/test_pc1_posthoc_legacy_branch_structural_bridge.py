from __future__ import annotations

import copy
import inspect
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

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
from core.platform.structure.service import StructuralAuthorityError
from core.platform.structure.posthoc_bridge import (
    EnsureLegacyBranchStructuralBridge,
    LegacyBranchRecord,
    LegacyBranchStructuralMapping,
    PC1PosthocLegacyBranchStructuralBridgeAuthority,
    PC1PosthocStructuralBridgeError,
)
from restaurant.c3.adapters import StructuralScopeAdapter
from restaurant.c3.service import CustomerSafeCheckoutPaymentRequestService


ROOT = Path(__file__).resolve().parents[2]
BASE = "192d0becb83929a0807537a80eea9b57559d5145"
BRIDGE_HEAD = "936451415a8ffcf033331194e50a4f606d37b87b"
AUTHORIZED = {
    "core/platform/structure/posthoc_bridge/__init__.py",
    "core/platform/structure/posthoc_bridge/contracts.py",
    "core/platform/structure/posthoc_bridge/service.py",
    "core/platform/structure/posthoc_bridge/sql_repository.py",
    "contracts/platform/v1/pc1_posthoc_legacy_branch_structural_bridge.json",
    "tests/contracts/test_pc1_posthoc_legacy_branch_structural_bridge.py",
}


class MemoryRepository:
    def __init__(self):
        self.tenants = {
            1: Tenant(1, "T1", "Tenant 1", TenantLifecycle.ACTIVE, "CM", "XAF", "fr-CM", "Africa/Douala"),
            2: Tenant(2, "T2", "Tenant 2", TenantLifecycle.ACTIVE, "CM", "XAF", "fr-CM", "Africa/Douala"),
        }
        self.organizations = {
            (1, 10): OrganizationUnit(10, UUID(int=10), 1, "WND", "Wine & Dine", "root", None, 100, True),
            (1, 11): OrganizationUnit(11, UUID(int=11), 1, "ALT", "Alternative", "operating_unit", None, 100, True),
            (2, 20): OrganizationUnit(20, UUID(int=20), 2, "OTHER", "Other", "root", None, 200, True),
        }
        self.legals = {
            (1, 100): LegalEntity(100, UUID(int=100), 1, "WND-CM", "Wine & Dine Cameroon"),
            (1, 101): LegalEntity(101, UUID(int=101), 1, "ALT-CM", "Alternative Cameroon"),
            (2, 200): LegalEntity(200, UUID(int=200), 2, "OTHER-CM", "Other Cameroon"),
        }
        self.locations = {
            (1, 20): Location(20, UUID(int=20), 1, "LOGPOM", "Logpom", LocationKind.PHYSICAL, 100, "Africa/Douala"),
            (1, 21): Location(21, UUID(int=21), 1, "BONAMOUSSADI", "Bonamoussadi", LocationKind.PHYSICAL, 100, "Africa/Douala"),
            (1, 22): Location(22, UUID(int=22), 1, "OTHER", "Other", LocationKind.PHYSICAL, 101, "Africa/Douala"),
            (1, 23): Location(23, UUID(int=23), 1, "VIRTUAL", "Virtual", LocationKind.VIRTUAL, 100, "Africa/Douala"),
            (2, 30): Location(30, UUID(int=30), 2, "OTHER", "Other", LocationKind.PHYSICAL, 200, "Africa/Douala"),
        }
        self.branches: dict[int, LegacyBranchRecord] = {}
        self.mappings: dict[int, LegacyBranchStructuralMapping] = {}
        self.next_branch_id = 1
        self.events: list[str] = []
        self.fail_after_branch = False
        self._lock = threading.RLock()

    @contextmanager
    def atomic(self):
        with self._lock:
            snapshot = (
                copy.deepcopy(self.branches),
                copy.deepcopy(self.mappings),
                self.next_branch_id,
                list(self.events),
            )
            try:
                yield
            except Exception:
                self.branches, self.mappings, self.next_branch_id, self.events = snapshot
                raise

    def serialize(self, command):
        return None

    def resolve_context(self, command):
        tenant = self.tenants.get(command.tenant_id)
        if tenant is None:
            raise StructuralAuthorityError("tenant_not_found")
        organization = self.organizations.get((command.tenant_id, command.organization_unit_id))
        if organization is None:
            raise StructuralAuthorityError("organization_not_found_or_cross_tenant")
        location = self.locations.get((command.tenant_id, command.location_id))
        if location is None:
            raise StructuralAuthorityError("location_not_found_or_cross_tenant")
        ids = {v for v in (organization.legal_entity_id, location.legal_entity_id) if v is not None}
        if len(ids) > 1:
            raise StructuralAuthorityError("ambiguous_legal_entity_context")
        legal = self.legals.get((command.tenant_id, next(iter(ids)))) if ids else None
        return StructuralContext(tenant, organization, legal, location, (organization.id,))

    def mapping_by_organization(self, tenant_id, organization_unit_id):
        return next(
            (
                row for row in self.mappings.values()
                if row.tenant_id == tenant_id and row.organization_unit_id == organization_unit_id
            ),
            None,
        )

    def mapping_by_location(self, tenant_id, location_id):
        return next(
            (
                row for row in self.mappings.values()
                if row.tenant_id == tenant_id and row.location_id == location_id
            ),
            None,
        )

    def branch_by_id(self, tenant_id, branch_id):
        row = self.branches.get(branch_id)
        return row if row and row.tenant_id == tenant_id else None

    def branches_by_code(self, tenant_id, branch_code):
        return tuple(
            row for row in self.branches.values()
            if row.tenant_id == tenant_id and row.branch_code == branch_code
        )

    def create_branch(self, tenant_id, branch_code, name):
        row = LegacyBranchRecord(self.next_branch_id, tenant_id, branch_code, name, True)
        self.next_branch_id += 1
        self.branches[row.id] = row
        self.events.append("branch")
        return row

    def create_mapping(self, command, branch_id):
        if self.fail_after_branch:
            raise RuntimeError("injected mapping failure")
        row = LegacyBranchStructuralMapping(
            command.tenant_id, branch_id, command.organization_unit_id, command.location_id
        )
        self.mappings[branch_id] = row
        self.events.append("mapping")
        return row

    def resolve_branch(self, tenant_id, branch_id):
        mapping = self.mappings.get(branch_id)
        if mapping is None or mapping.tenant_id != tenant_id:
            raise StructuralAuthorityError("unmapped_legacy_branch")
        return self.resolve_context(
            EnsureLegacyBranchStructuralBridge(
                tenant_id, mapping.organization_unit_id, mapping.location_id
            )
        )


def _authority(repo=None):
    repo = repo or MemoryRepository()
    return PC1PosthocLegacyBranchStructuralBridgeAuthority(repo), repo


def _cmd(org=10, loc=20, tenant=1):
    return EnsureLegacyBranchStructuralBridge(tenant, org, loc)


def _historical_changed_paths():
    changed = subprocess.run(
        ["git", "diff", "--name-only", BASE, BRIDGE_HEAD],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.splitlines()
    return {path.replace("\\", "/") for path in changed if path.strip()}


def test_01_happy_path_creates_one_branch_and_one_mapping():
    authority, repo = _authority()
    result = authority.ensure(_cmd())
    assert result.legacy_branch_id == 1 and len(repo.branches) == len(repo.mappings) == 1
    assert repo.events == ["branch", "mapping"]


def test_02_created_branch_resolves_exact_canonical_context():
    authority, repo = _authority()
    result = authority.ensure(_cmd())
    context = repo.resolve_branch(1, result.legacy_branch_id)
    assert context.organization_unit.id == 10
    assert context.location.id == 20
    assert context.legal_entity.id == 100


def test_03_exact_replay_returns_same_branch_id():
    authority, _ = _authority()
    first = authority.ensure(_cmd())
    second = authority.ensure(_cmd())
    assert first.legacy_branch_id == second.legacy_branch_id and second.replayed is True


def test_04_replay_branch_and_mapping_counts_unchanged():
    authority, repo = _authority()
    authority.ensure(_cmd())
    before = (len(repo.branches), len(repo.mappings))
    authority.ensure(_cmd())
    assert (len(repo.branches), len(repo.mappings)) == before == (1, 1)


def test_05_same_organization_different_location_fails():
    authority, repo = _authority()
    authority.ensure(_cmd())
    with pytest.raises(PC1PosthocStructuralBridgeError, match="incompatible_existing_structural_mapping"):
        authority.ensure(_cmd(loc=21))
    assert len(repo.branches) == len(repo.mappings) == 1


def test_06_same_location_different_organization_fails():
    authority, repo = _authority()
    authority.ensure(_cmd())
    with pytest.raises(PC1PosthocStructuralBridgeError, match="incompatible_existing_structural_mapping"):
        authority.ensure(_cmd(org=11))
    assert len(repo.branches) == len(repo.mappings) == 1


def test_07_cross_tenant_organization_fails_with_zero_writes():
    authority, repo = _authority()
    with pytest.raises(StructuralAuthorityError, match="organization_not_found_or_cross_tenant"):
        authority.ensure(_cmd(org=20))
    assert not repo.branches and not repo.mappings


def test_08_cross_tenant_location_fails_with_zero_writes():
    authority, repo = _authority()
    with pytest.raises(StructuralAuthorityError, match="location_not_found_or_cross_tenant"):
        authority.ensure(_cmd(loc=30))
    assert not repo.branches and not repo.mappings


def test_09_conflicting_legal_entity_fails_with_zero_writes():
    authority, repo = _authority()
    with pytest.raises(StructuralAuthorityError, match="ambiguous_legal_entity_context"):
        authority.ensure(_cmd(loc=22))
    assert not repo.branches and not repo.mappings


def test_10_inactive_or_suspended_tenant_fails_with_zero_writes():
    authority, repo = _authority()
    repo.tenants[1] = replace(repo.tenants[1], lifecycle=TenantLifecycle.SUSPENDED)
    with pytest.raises(PC1PosthocStructuralBridgeError, match="tenant_not_active"):
        authority.ensure(_cmd())
    assert not repo.branches and not repo.mappings


def test_11_inactive_organization_fails_with_zero_writes():
    authority, repo = _authority()
    repo.organizations[(1, 10)] = replace(repo.organizations[(1, 10)], active=False)
    with pytest.raises(PC1PosthocStructuralBridgeError, match="organization_inactive"):
        authority.ensure(_cmd())
    assert not repo.branches and not repo.mappings


def test_12_inactive_location_fails_with_zero_writes():
    authority, repo = _authority()
    repo.locations[(1, 20)] = replace(repo.locations[(1, 20)], active=False)
    with pytest.raises(PC1PosthocStructuralBridgeError, match="location_inactive"):
        authority.ensure(_cmd())
    assert not repo.branches and not repo.mappings


def test_13_non_physical_location_fails():
    authority, repo = _authority()
    with pytest.raises(PC1PosthocStructuralBridgeError, match="physical_location_required"):
        authority.ensure(_cmd(loc=23))
    assert not repo.branches and not repo.mappings


def test_14_unrelated_tenant_qualified_branch_code_collision_fails_closed():
    authority, repo = _authority()
    repo.branches[99] = LegacyBranchRecord(99, 1, "LOGPOM", "Unrelated", True)
    with pytest.raises(PC1PosthocStructuralBridgeError, match="legacy_branch_code_collision"):
        authority.ensure(_cmd())
    assert set(repo.branches) == {99} and not repo.mappings


def test_15_concurrent_identical_commands_create_one_branch_and_mapping():
    authority, repo = _authority()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: authority.ensure(_cmd()), range(2)))
    assert {row.legacy_branch_id for row in results} == {1}
    assert len(repo.branches) == len(repo.mappings) == 1
    assert sorted(row.replayed for row in results) == [False, True]


def test_16_injected_failure_between_branch_and_mapping_rolls_back_both():
    authority, repo = _authority()
    repo.fail_after_branch = True
    with pytest.raises(RuntimeError, match="injected mapping failure"):
        authority.ensure(_cmd())
    assert not repo.branches and not repo.mappings and repo.next_branch_id == 1


def test_17_canonical_structural_counts_unchanged():
    authority, repo = _authority()
    before = (len(repo.tenants), len(repo.organizations), len(repo.locations), len(repo.legals))
    authority.ensure(_cmd())
    after = (len(repo.tenants), len(repo.organizations), len(repo.locations), len(repo.legals))
    assert after == before


def test_18_existing_c3_structural_adapter_resolves_created_branch():
    authority, repo = _authority()
    result = authority.ensure(_cmd())

    class ExistingAuthority:
        def resolve(self, *, tenant_id, legacy_branch_id):
            return repo.resolve_branch(tenant_id, legacy_branch_id)

    context = StructuralScopeAdapter(ExistingAuthority()).resolve(
        tenant_id=1, branch_id=result.legacy_branch_id
    )
    assert context.organization_unit.id == 10 and context.location.id == 20


def test_19_c3_caller_still_cannot_supply_canonical_org_or_location():
    parameters = inspect.signature(
        CustomerSafeCheckoutPaymentRequestService.create_payment_request
    ).parameters
    assert "organization_unit_id" not in parameters
    assert "location_id" not in parameters


def test_20_zero_finance_payment_settlement_or_treasury_effect():
    source = (ROOT / "core/platform/structure/posthoc_bridge/service.py").read_text().lower()
    for token in ("core.domain.finance", "payment_settlement", "treasury", "journal"):
        assert token not in source


def test_21_zero_gateway_effect():
    source = (ROOT / "core/platform/structure/posthoc_bridge/service.py").read_text().lower()
    assert "gateway" not in source and "provider" not in source


def test_22_zero_pc4_configuration_effect():
    source = (ROOT / "core/platform/structure/posthoc_bridge/service.py").read_text().lower()
    assert "operating_context" not in source and "configuration" not in source


def test_23_zero_r1_order_effect():
    source = (ROOT / "core/platform/structure/posthoc_bridge/service.py").read_text().lower()
    assert "restaurant.r1" not in source and "open_order" not in source and "add_line" not in source


def test_24_alembic_and_schema_head_unchanged():
    changed = _historical_changed_paths()
    assert not any(path.startswith("alembic") for path in changed)
    assert not any("migration" in path.lower() for path in changed)


def test_25_exact_source_boundary_only():
    assert _historical_changed_paths() == AUTHORIZED
