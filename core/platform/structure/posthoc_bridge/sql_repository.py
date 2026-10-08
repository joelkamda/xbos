"""PostgreSQL persistence for the additive PC1 posthoc structural bridge."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.platform.structure.service import StructuralAuthority
from core.platform.structure.sql_repository import SQLStructuralRepository

from .contracts import (
    EnsureLegacyBranchStructuralBridge,
    LegacyBranchRecord,
    LegacyBranchStructuralMapping,
)


class SQLPC1PosthocLegacyBranchStructuralBridgeRepository:
    def __init__(self, session: Session):
        self.session = session
        self.structural = StructuralAuthority(SQLStructuralRepository(session))

    @contextmanager
    def atomic(self):
        if self.session.in_transaction():
            with self.session.begin_nested():
                yield
        else:
            with self.session.begin():
                yield

    def serialize(self, command: EnsureLegacyBranchStructuralBridge) -> None:
        key = (
            f"pc1-posthoc-legacy-branch:{command.tenant_id}:"
            f"{command.organization_unit_id}:{command.location_id}"
        )
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": key},
        )

    def resolve_context(self, command: EnsureLegacyBranchStructuralBridge):
        return self.structural.resolve(
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            location_id=command.location_id,
        )

    @staticmethod
    def _mapping(row) -> LegacyBranchStructuralMapping | None:
        if row is None:
            return None
        return LegacyBranchStructuralMapping(
            tenant_id=int(row.tenant_id),
            branch_id=int(row.branch_id),
            organization_unit_id=int(row.organization_unit_id),
            location_id=int(row.location_id),
        )

    def mapping_by_organization(
        self, tenant_id: int, organization_unit_id: int
    ) -> LegacyBranchStructuralMapping | None:
        row = self.session.execute(
            text(
                "SELECT tenant_id,branch_id,organization_unit_id,location_id "
                "FROM legacy_branch_structural_mappings "
                "WHERE tenant_id=:tenant AND organization_unit_id=:organization FOR UPDATE"
            ),
            {"tenant": tenant_id, "organization": organization_unit_id},
        ).first()
        return self._mapping(row)

    def mapping_by_location(
        self, tenant_id: int, location_id: int
    ) -> LegacyBranchStructuralMapping | None:
        row = self.session.execute(
            text(
                "SELECT tenant_id,branch_id,organization_unit_id,location_id "
                "FROM legacy_branch_structural_mappings "
                "WHERE tenant_id=:tenant AND location_id=:location FOR UPDATE"
            ),
            {"tenant": tenant_id, "location": location_id},
        ).first()
        return self._mapping(row)

    @staticmethod
    def _branch(row) -> LegacyBranchRecord | None:
        if row is None:
            return None
        return LegacyBranchRecord(
            id=int(row.id),
            tenant_id=int(row.tenant_id),
            branch_code=str(row.branch_code),
            name=str(row.name),
            is_active=bool(row.is_active),
        )

    def branch_by_id(self, tenant_id: int, branch_id: int) -> LegacyBranchRecord | None:
        row = self.session.execute(
            text(
                "SELECT id,tenant_id,branch_code,name,is_active FROM branches "
                "WHERE tenant_id=:tenant AND id=:branch"
            ),
            {"tenant": tenant_id, "branch": branch_id},
        ).first()
        return self._branch(row)

    def branches_by_code(self, tenant_id: int, branch_code: str) -> tuple[LegacyBranchRecord, ...]:
        rows = self.session.execute(
            text(
                "SELECT id,tenant_id,branch_code,name,is_active FROM branches "
                "WHERE tenant_id=:tenant AND branch_code=:code ORDER BY id FOR UPDATE"
            ),
            {"tenant": tenant_id, "code": branch_code},
        ).all()
        return tuple(self._branch(row) for row in rows)

    def create_branch(self, tenant_id: int, branch_code: str, name: str) -> LegacyBranchRecord:
        row = self.session.execute(
            text(
                "INSERT INTO branches(tenant_id,branch_code,name,is_active) "
                "VALUES(:tenant,:code,:name,TRUE) "
                "RETURNING id,tenant_id,branch_code,name,is_active"
            ),
            {"tenant": tenant_id, "code": branch_code, "name": name},
        ).first()
        return self._branch(row)

    def create_mapping(
        self, command: EnsureLegacyBranchStructuralBridge, branch_id: int
    ) -> LegacyBranchStructuralMapping:
        row = self.session.execute(
            text(
                "INSERT INTO legacy_branch_structural_mappings"
                "(tenant_id,branch_id,organization_unit_id,location_id) "
                "VALUES(:tenant,:branch,:organization,:location) "
                "RETURNING tenant_id,branch_id,organization_unit_id,location_id"
            ),
            {
                "tenant": command.tenant_id,
                "branch": branch_id,
                "organization": command.organization_unit_id,
                "location": command.location_id,
            },
        ).first()
        return self._mapping(row)

    def resolve_branch(self, tenant_id: int, branch_id: int):
        return self.structural.resolve(tenant_id=tenant_id, legacy_branch_id=branch_id)
