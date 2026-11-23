-- PA additive synthetic TEST-only authorization schema.
-- No genuine PC5 issuer, account enrollment, or financial effect.
CREATE TABLE v24_pa_test_publish_policy (
  tenant_id BIGINT NOT NULL CHECK(tenant_id>0),
  branch_id BIGINT NOT NULL CHECK(branch_id>0),
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  minimum_issuer_epoch BIGINT NOT NULL CHECK(minimum_issuer_epoch>0),
  PRIMARY KEY (tenant_id,branch_id)
);
CREATE TABLE v24_pa_test_publish_grants (
  tenant_id BIGINT NOT NULL CHECK(tenant_id>0),
  branch_id BIGINT NOT NULL CHECK(branch_id>0),
  actor_ref TEXT NOT NULL REFERENCES v3r_operator(username),
  permission TEXT NOT NULL CHECK(permission='restaurant.product.publish.test'),
  issuer_epoch BIGINT NOT NULL CHECK(issuer_epoch>0),
  valid_from TIMESTAMPTZ NOT NULL,
  valid_until TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  grade TEXT NOT NULL CHECK(grade='SYNTHETIC_PG17_PERMISSION_NOT_GENUINE_PC5'),
  CHECK(valid_until>valid_from),
  PRIMARY KEY(tenant_id,branch_id,actor_ref,permission)
);
