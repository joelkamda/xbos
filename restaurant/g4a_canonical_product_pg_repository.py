"""PostgreSQL17-backed G4-A product review candidate transaction.

The table is a NEW, explicit G4-A TEST CANDIDATE, not SO1's operative catalog
or WND production. No startup import / Alembic migration or implicit DB
connection. Caller must provide a separate, approved connection factory.
Row locks + CAS + one audit insert are committed or rolled back together.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable
from uuid import UUID

from psycopg2.extras import RealDictCursor

from restaurant.g4a_canonical_product_publication import (
    CanonicalPublishProof, ProductReviewSnapshot, ProductState, ZonePriceDraft,
)


class PgProductTransaction:
    def __init__(self, connection):
        self.connection=connection
        self.locked=None

    def load_for_update(self,tenant_id:int,location_id:int,product_public_id:UUID):
        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT * FROM g4a_product_review_candidates
                   WHERE tenant_id=%s AND location_id=%s AND public_id=%s
                   FOR UPDATE""",
                (tenant_id, location_id, str(product_public_id)))
            row=cursor.fetchone()
        if row is None:return None
        prices=tuple(ZonePriceDraft(
            zone, int(row["zone_prices"][zone]["amount_xaf"]),
            int(row["zone_prices"][zone]["revision"]))
            for zone in ("MAIN","VIP","BAR"))
        result=ProductReviewSnapshot(
            UUID(str(row["public_id"])),row["tenant_id"],row["location_id"],
            row["creator_identity_id"],UUID(str(row["atomic_unit_public_id"])),
            row["atomic_unit_version"],row["semantic_qualified_code"],
            row["semantic_version"],row["pack_code"],row["pack_version"],
            row["revision"],ProductState(row["state"]),prices)
        self.locked=result
        return result

    def publish_cas(self,*,snapshot:ProductReviewSnapshot,
                    reviewer_identity_id:int,expected_revision:int,
                    expected_price_revisions:tuple[int,int,int],
                    pack_manifest_sha256:str,pc3_semantic_version:int,
                    so1_atomic_unit_version:int,finance_binding_version:int,
                    correlation_id:str):
        if self.locked!=snapshot:
            return None
        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """UPDATE g4a_product_review_candidates
                   SET state='published',revision=revision+1,
                       reviewer_identity_id=%s
                   WHERE public_id=%s AND tenant_id=%s AND location_id=%s
                     AND state='review' AND revision=%s
                     AND (zone_prices->'MAIN'->>'revision')::integer=%s
                     AND (zone_prices->'VIP'->>'revision')::integer=%s
                     AND (zone_prices->'BAR'->>'revision')::integer=%s
                   RETURNING revision""",
                (reviewer_identity_id,str(snapshot.public_id),
                 snapshot.tenant_id,snapshot.location_id,expected_revision,
                 *expected_price_revisions))
            row=cursor.fetchone()
            if row is None:return None
            cursor.execute(
                """INSERT INTO g4a_product_candidate_audit (
                    tenant_id,location_id,product_public_id,
                    reviewer_identity_id,source_revision,
                    committed_revision,correlation_id,
                    pack_manifest_sha256,pc3_semantic_version,
                    so1_atomic_unit_version,finance_binding_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (snapshot.tenant_id,snapshot.location_id,
                 str(snapshot.public_id),reviewer_identity_id,
                 expected_revision,row["revision"],correlation_id,
                 pack_manifest_sha256,pc3_semantic_version,
                 so1_atomic_unit_version,finance_binding_version))
        return CanonicalPublishProof(
            snapshot.tenant_id,snapshot.location_id,snapshot.public_id,
            row["revision"],reviewer_identity_id,pc3_semantic_version,
            pack_manifest_sha256,so1_atomic_unit_version,
            finance_binding_version,expected_price_revisions)


class PgProductCandidateStore:
    def __init__(self, connect:Callable):
        if not callable(connect):
            raise TypeError("G4A_PG_CONNECTION_FACTORY_REQUIRED")
        self._connect=connect

    @contextmanager
    def transaction(self):
        connection=self._connect()
        params=connection.get_dsn_parameters()
        # The candidate repository must never accidentally point at xbos, WND
        # or any future canonical database. This module is TEST-only until
        # replaced by an independently admitted repository/migration.
        if (params.get("dbname")!="g4a_v24_native_product_test"
                or params.get("host")!="127.0.0.1"
                or str(params.get("port"))!="55449"):
            connection.close()
            raise RuntimeError("G4A_CANDIDATE_WRITES_NOT_PERMITTED_OUTSIDE_TEST_DB")
        if connection.autocommit:
            connection.close()
            raise RuntimeError("G4A_AUTOCOMMIT_DENIED")
        try:
            tx=PgProductTransaction(connection)
            yield tx
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
