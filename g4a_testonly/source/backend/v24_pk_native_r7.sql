-- R7 PK/G4-A detached TEST only. Run AFTER inherited v24_init_r6.sql.
-- Synthetic authority fixtures only; no real issuer, PC5, Finance or live WND.
-- One source of mutable product+zone amounts: v24_product_workflow.
-- Price revisions are per-zone concurrency metadata, not duplicate price records.
ALTER TABLE v24_product_workflow
  ADD COLUMN main_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(main_price_revision>=1),
  ADD COLUMN vip_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(vip_price_revision>=1),
  ADD COLUMN bar_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(bar_price_revision>=1);

CREATE FUNCTION v24_pk_zone_version_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.main_xaf IS DISTINCT FROM OLD.main_xaf THEN
    NEW.main_price_revision := OLD.main_price_revision + 1;
  ELSE
    NEW.main_price_revision := OLD.main_price_revision;
  END IF;
  IF NEW.vip_xaf IS DISTINCT FROM OLD.vip_xaf THEN
    NEW.vip_price_revision := OLD.vip_price_revision + 1;
  ELSE
    NEW.vip_price_revision := OLD.vip_price_revision;
  END IF;
  IF NEW.bar_xaf IS DISTINCT FROM OLD.bar_xaf THEN
    NEW.bar_price_revision := OLD.bar_price_revision + 1;
  ELSE
    NEW.bar_price_revision := OLD.bar_price_revision;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER v24_pk_zone_versions_on_edit
BEFORE UPDATE OF main_xaf,vip_xaf,bar_xaf ON v24_product_workflow
FOR EACH ROW EXECUTE FUNCTION v24_pk_zone_version_trigger();

CREATE TABLE v24_pk_test_pack_readback (
 tenant_id INT NOT NULL CHECK(tenant_id=920002),
 branch_id INT NOT NULL CHECK(branch_id=1),
 pack_code TEXT NOT NULL CHECK(pack_code='industry.restaurant'),
 version TEXT NOT NULL, manifest_sha256 TEXT NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 cert_sha256 TEXT NOT NULL CHECK(cert_sha256 ~ '^[a-f0-9]{64}$'),
 version_revision INT NOT NULL CHECK(version_revision>0),
 issuer_epoch INT NOT NULL CHECK(issuer_epoch>0),
 min_issuer_epoch INT NOT NULL CHECK(min_issuer_epoch>0),
 certified_axes JSONB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('ACTIVE_SOURCE','DISABLED_SOURCE','REVOKED_SOURCE')),
 source_grade TEXT NOT NULL DEFAULT 'SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'
   CHECK(source_grade='SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'),
 PRIMARY KEY(tenant_id,branch_id,pack_code)
);

CREATE TABLE v24_pk_test_policy_readback (
 tenant_id INT NOT NULL CHECK(tenant_id=920002),
 branch_id INT NOT NULL CHECK(branch_id=1),
 category_code TEXT NOT NULL,
 family TEXT NOT NULL CHECK(family IN ('bar','kitchen','other')),
 unit_code TEXT NOT NULL,
 uom_precision INT NOT NULL CHECK(uom_precision BETWEEN 0 AND 6),
 pc3_policy_revision INT NOT NULL CHECK(pc3_policy_revision>0),
 pc3_concept_sha256 TEXT NOT NULL CHECK(pc3_concept_sha256 ~ '^[a-f0-9]{64}$'),
 tax_policy_code TEXT NOT NULL,
 tax_policy_revision INT NOT NULL CHECK(tax_policy_revision>0),
 revenue_account_code TEXT NOT NULL,
 inventory_account_code TEXT,
 cogs_account_code TEXT,
 stock_tracked BOOLEAN NOT NULL,
 valid_from TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ,
 source_grade TEXT NOT NULL DEFAULT 'SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'
   CHECK(source_grade='SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'),
 PRIMARY KEY(tenant_id,branch_id,category_code,family,unit_code),
 CHECK(valid_until IS NULL OR valid_until>valid_from),
 CHECK((NOT stock_tracked AND inventory_account_code IS NULL AND cogs_account_code IS NULL)
    OR (stock_tracked AND inventory_account_code IS NOT NULL AND cogs_account_code IS NOT NULL))
);

-- Synthetic TEST fixtures; fabricated policy IDs are never claimed as WND/PC3/SOF authoritative.
INSERT INTO v24_pk_test_pack_readback
(tenant_id,branch_id,pack_code,version,manifest_sha256,cert_sha256,version_revision,
 issuer_epoch,min_issuer_epoch,certified_axes,state)
VALUES
(920002,1,'industry.restaurant','SYNTHETIC-R7','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
 1,4,4,
 '["architecture","tenant_isolation","migration_compatibility","authorization","semantics","finance","shared_operations","xa","manifest"]'::jsonb,
 'ACTIVE_SOURCE');

INSERT INTO v24_pk_test_policy_readback
(tenant_id,branch_id,category_code,family,unit_code,uom_precision,pc3_policy_revision,
 pc3_concept_sha256,tax_policy_code,tax_policy_revision,revenue_account_code,
 inventory_account_code,cogs_account_code,stock_tracked,valid_from)
VALUES
(920002,1,'MOCK DRINK','bar','BOTTLE',0,1,
 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
 'VAT_TEST_R7',1,'SALES_BAR_TEST','DRINK_STOCK_TEST','DRINK_COGS_TEST',TRUE,
 '2026-01-01T00:00:00+01:00');
