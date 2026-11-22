"""R7 TEST-only native product publication PK guard.

All readbacks come from isolated native PostgreSQL (not from API caller).
Both the product and version metadata are locked before the single publish
transaction. Fixtures are synthetic and never assert genuine PC3/SOF/PA/PK
issuer or official Finance authority.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from fastapi import HTTPException

from pack_platform.v24_pk_config_preflight import (
    TenantContext, PackReadback, CanonicalMapping,
    MerchantProduct, ZonePriceReadback,
    PKConfigDenied, preview_pack_tax_account_and_price_cas,
)

SYNTHETIC_GRADE = "SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED"
ZONES=("MAIN","VIP","BAR")
PRICE_CODES={"MAIN":"retail","VIP":"vip_lounge","BAR":"bar_premium"}


def guard_synthetic_product_publish(c, p, expected_price_revisions, actor,
                                   tenant_id, branch_id, *, at=None):
    """Read under the caller's PostgreSQL transaction after SELECT FOR UPDATE.

    Publication must fail if the pack or canonical account/tax mapping is
    unavailable, expired, revoked, or stale. No externally supplied policy
    or pack fixture is trusted. Downstream R7 publication remains TEST grade.
    """
    if type(expected_price_revisions) is not tuple or len(expected_price_revisions)!=3:
        raise HTTPException(status_code=409,detail="PK_PRICE_REVISIONS_REQUIRED")
    if any(type(n) is not int or n<1 for n in expected_price_revisions):
        raise HTTPException(status_code=409,detail="PK_PRICE_REVISIONS_INVALID")
    c.execute("""SELECT * FROM v24_pk_test_pack_readback
                 WHERE tenant_id=%s AND branch_id=%s AND pack_code='industry.restaurant'
                 FOR SHARE""", (tenant_id,branch_id))
    packrow=c.fetchone()
    if packrow is None:
        raise HTTPException(status_code=409,detail="PK_PACK_RECORD_NOT_ADMITTED")
    c.execute("""SELECT * FROM v24_pk_test_policy_readback
                 WHERE tenant_id=%s AND branch_id=%s
                 AND category_code=%s AND family=%s AND unit_code=%s
                 FOR SHARE""", (tenant_id,branch_id,p["category"],p["family"],p["unit"]))
    mappingrow=c.fetchone()
    if mappingrow is None:
        raise HTTPException(status_code=409,detail="PK_TAX_ACCOUNT_POLICY_NOT_CONFIGURED")
    at=at or datetime.now(timezone.utc)
    if p["stock_qty"] is None:
        stock_tracked=False
    else:
        stock_tracked=True
    try:
        context=TenantContext(tenant_id,branch_id,actor)
        pack=PackReadback(
            tenant_id=packrow["tenant_id"],
            branch_id=packrow["branch_id"],
            pack_code=packrow["pack_code"],
            version=packrow["version"],
            manifest_sha256=packrow["manifest_sha256"],
            cert_sha256=packrow["cert_sha256"],
            version_revision=packrow["version_revision"],
            issuer_epoch=packrow["issuer_epoch"],
            certified_axes=frozenset(packrow["certified_axes"]),
            state=packrow["state"],
        )
        mapping=CanonicalMapping(
            tenant_id=mappingrow["tenant_id"],
            branch_id=mappingrow["branch_id"],
            sku=p["sku"],
            category_code=mappingrow["category_code"],
            family=mappingrow["family"],
            unit_code=mappingrow["unit_code"],
            uom_precision=mappingrow["uom_precision"],
            pc3_policy_revision=mappingrow["pc3_policy_revision"],
            pc3_concept_sha256=mappingrow["pc3_concept_sha256"],
            tax_policy_code=mappingrow["tax_policy_code"],
            tax_policy_revision=mappingrow["tax_policy_revision"],
            revenue_account_code=mappingrow["revenue_account_code"],
            inventory_account_code=mappingrow["inventory_account_code"],
            cogs_account_code=mappingrow["cogs_account_code"],
            stock_tracked=mappingrow["stock_tracked"],
            valid_from=mappingrow["valid_from"],
            valid_until=mappingrow["valid_until"],
        )
        product=MerchantProduct(
            tenant_id=tenant_id,branch_id=branch_id,sku=p["sku"],
            category_code=p["category"],family=p["family"],
            unit_code=p["unit"],draft_revision=p["revision"],
            desired_price_amounts=(p["main_xaf"],p["vip_xaf"],p["bar_xaf"]),
            stock_tracked=stock_tracked,
        )
        prices=tuple(
            ZonePriceReadback(
                tenant_id=tenant_id,branch_id=branch_id,sku=p["sku"],
                zone=zone,price_code=PRICE_CODES[zone],
                amount_xaf=p[zone.lower()+"_xaf"],
                price_revision=p[zone.lower()+"_price_revision"],
                price_row_sha256=sha256(
                    f"TEST-WORKFLOW:{tenant_id}:{branch_id}:{p['sku']}:{zone}:"
                    f"{p[zone.lower()+'_xaf']}:{p[zone.lower()+'_price_revision']}"
                    .encode("utf-8")).hexdigest(),
            )
            for zone in ZONES
        )
        receipt=preview_pack_tax_account_and_price_cas(
            context=context,pack=pack,mapping=mapping,
            product=product,current_prices=prices,
            expected_product_revision=p["revision"],
            expected_price_revisions=expected_price_revisions,
            minimum_issuer_epoch=packrow["min_issuer_epoch"],
            at=at,
        )
    except (PKConfigDenied,TypeError,KeyError,ValueError) as exc:
        code=getattr(exc,"code","PK_INCOMPATIBLE_NATIVE_TEST_RECORD")
        raise HTTPException(status_code=409,detail=code) from None
    return {
        "sourceGrade":SYNTHETIC_GRADE,
        "grade":"NATIVE_PG_TEST_WORKFLOW_PRECHECK",
        "preflightDigest":receipt.digest_sha256,
        "mappingRevision":mapping.pc3_policy_revision,
        "taxRevision":mapping.tax_policy_revision,
        "packRevision":pack.version_revision,
        "priceRevisions":list(expected_price_revisions),
        "actualPc5":False,
        "packSigningVerified":False,
        "officialFinancePosted":False,
    }
