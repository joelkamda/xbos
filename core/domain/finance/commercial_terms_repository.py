"""Tenant-scoped source authority for M5.2 commercial components."""

from __future__ import annotations

from sqlalchemy import text

from .commercial_terms_contract import CommercialTermsError


EXPECTED_SOURCE_KINDS = {
    "discount": "commercial_adjustment",
    "complimentary": "commercial_adjustment",
    "customer_service_fee": "commercial_transaction_line",
    "output_tax": "commercial_transaction_component",
}


class CommercialTermsRepository:
    @staticmethod
    def source_authority(session, *, tenant_id: int, organization_unit_id: int, source_record_id: int, component_type: str):
        row = session.execute(text("""
            SELECT id,tenant_id,organization_unit_id,aggregate_type,retired_at
            FROM public.kernel_source_records
            WHERE tenant_id=:tenant AND id=:source
        """), {"tenant": tenant_id, "source": source_record_id}).mappings().one_or_none()
        if row is None:
            raise CommercialTermsError("source_not_found", "component source is missing or belongs to another tenant")
        if row["organization_unit_id"] not in (None, organization_unit_id):
            raise CommercialTermsError("source_scope_mismatch", "component source belongs to another organization")
        if row["retired_at"] is not None:
            raise CommercialTermsError("source_retired", "retired component source cannot create financial truth")
        if row["aggregate_type"] != EXPECTED_SOURCE_KINDS[component_type]:
            raise CommercialTermsError("source_kind_mismatch", "component source kind is not authoritative")
        return row
