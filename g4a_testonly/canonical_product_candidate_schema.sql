-- G4-A TEST CANDIDATE ONLY. Not an Alembic migration, SO1 public catalog,
-- canonical Finance or production WND schema. Explicit no-egress test DDL.
CREATE TABLE g4a_product_review_candidates (
  public_id UUID PRIMARY KEY,
  tenant_id INTEGER NOT NULL CHECK (tenant_id > 0),
  location_id INTEGER NOT NULL CHECK (location_id > 0),
  creator_identity_id INTEGER NOT NULL CHECK (creator_identity_id > 0),
  reviewer_identity_id INTEGER,
  atomic_unit_public_id UUID NOT NULL,
  atomic_unit_version INTEGER NOT NULL CHECK (atomic_unit_version > 0),
  semantic_qualified_code TEXT NOT NULL,
  semantic_version INTEGER NOT NULL CHECK (semantic_version > 0),
  pack_code TEXT NOT NULL,
  pack_version TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  state TEXT NOT NULL CHECK (state IN ('review','published')),
  zone_prices JSONB NOT NULL,
  CHECK (jsonb_typeof(zone_prices)='object'),
  CHECK (zone_prices ? 'MAIN' AND zone_prices ? 'VIP' AND zone_prices ? 'BAR')
);
CREATE UNIQUE INDEX g4a_candidate_tenant_location_product
  ON g4a_product_review_candidates (tenant_id,location_id,public_id);
CREATE TABLE g4a_product_candidate_audit (
  sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id INTEGER NOT NULL CHECK(tenant_id>0),
  location_id INTEGER NOT NULL CHECK(location_id>0),
  product_public_id UUID NOT NULL REFERENCES g4a_product_review_candidates(public_id),
  reviewer_identity_id INTEGER NOT NULL CHECK(reviewer_identity_id>0),
  source_revision INTEGER NOT NULL,
  committed_revision INTEGER NOT NULL,
  correlation_id TEXT NOT NULL,
  pack_manifest_sha256 TEXT NOT NULL CHECK(length(pack_manifest_sha256)=64),
  pc3_semantic_version INTEGER NOT NULL,
  so1_atomic_unit_version INTEGER NOT NULL,
  finance_binding_version INTEGER NOT NULL,
  UNIQUE (tenant_id,location_id,product_public_id,committed_revision),
  UNIQUE (tenant_id,location_id,correlation_id)
);
