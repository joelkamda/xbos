"""PK D7-08/09 remaining G4-A contract checks. Synthetic, no PC5 or SQL."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import pytest

from pack_platform.v24_pk_config_preflight import (
    GRADE, CODES, ZONES, CanonicalMapping, MerchantProduct,
    PackReadback, PKConfigDenied, Preflight, TenantContext,
    ZonePriceReadback, preview_pack_tax_account_and_price_cas,
)

WAT=timezone(timedelta(hours=1))
NOW=datetime(2026,11,22,12,0,tzinfo=WAT)
TENANT=920002
BRANCH=1
SKU="V24-SYNTH-PK-1"
CTX=TenantContext(TENANT,BRANCH,"merchant_synthetic")
PACK=PackReadback(
    TENANT,BRANCH,"industry.restaurant","3.0.0",
    "a"*64,"b"*64,8,10,frozenset((
       "architecture","tenant_isolation","migration_compatibility",
       "authorization","semantics","finance",
       "shared_operations","xa","manifest")),"ACTIVE_SOURCE",
)
MAPPING=CanonicalMapping(
    TENANT,BRANCH,SKU,"SYNTHETIC-DRINKS","bar","BOTTLE",0,
    6,"c"*64,"VAT_TEST",4,"SALES_BAR_TEST","DRINKS_STOCK_TEST",
    "DRINKS_COGS_TEST",True,NOW-timedelta(days=1),None,
)
PRODUCT=MerchantProduct(
    TENANT,BRANCH,SKU,"SYNTHETIC-DRINKS","bar","BOTTLE",4,
    (1700,2300,1900),True,
)
PRICES=tuple(
    ZonePriceReadback(
       TENANT,BRANCH,SKU,z,CODES[z],amount,rev,digest)
    for z,amount,rev,digest in zip(
       ZONES,(1700,2300,1900),(2,3,1),("d"*64,"e"*64,"f"*64))
)
BASE=dict(
    context=CTX,pack=PACK,mapping=MAPPING,product=PRODUCT,
    current_prices=PRICES,expected_product_revision=4,
    expected_price_revisions=(2,3,1),
    minimum_issuer_epoch=10,at=NOW,
)

def review(**kwargs):
    values=dict(BASE)
    values.update(kwargs)
    return preview_pack_tax_account_and_price_cas(**values)

def denied(code,**kwargs):
    with pytest.raises(PKConfigDenied) as e:
        review(**kwargs)
    assert e.value.code==code

def test_synthetic_three_zone_tax_account_pack_readback_remains_nonoperative():
    p=review()
    assert p.sku==SKU and p.zones==ZONES
    assert p.status=="TEST_SOURCE_REVIEW_ELIGIBLE_NOT_AUTHORIZED"
    assert len(p.digest_sha256)==64
    assert p==review()
    for f in ("effective_permission","pc5_admitted","pack_certified_real",
              "can_publish","published","posted_finance","provider_paid"):
        assert getattr(p,f) is False

def test_no_database_or_network_helpers_exposed():
    p=review()
    assert not hasattr(p,"commit")
    assert not hasattr(p,"publish")
    assert not hasattr(p,"mark_paid")
    assert not hasattr(p,"issue_token")

@pytest.mark.parametrize("field",[
    "effective_permission","pc5_admitted","pack_certified_real",
    "can_publish","published","posted_finance","provider_paid",
])
def test_positive_preview_cannot_be_promoted_to_actual_right(field):
    with pytest.raises(PKConfigDenied) as exc:
        replace(review(),**{field:True})
    assert exc.value.code=="PK_PREVIEW_PRIVILEGE_ESCALATION_DENIED"

def test_immutable_preflight():
    with pytest.raises(FrozenInstanceError):
        review().can_publish=True

@pytest.mark.parametrize("field,value",[
    ("tenant_id",TENANT+1),
    ("branch_id",BRANCH+1),
])
def test_wrong_pack_scope_denied(field,value):
    denied("PK_CROSS_TENANT_BRANCH_SKU_DENIED",
           pack=replace(PACK,**{field:value}))

@pytest.mark.parametrize("field,value",[
    ("tenant_id",TENANT+1),
    ("branch_id",BRANCH+1),
    ("sku","OTHER-TEST-SKU"),
])
def test_wrong_mapping_scope_denied(field,value):
    denied("PK_CROSS_TENANT_BRANCH_SKU_DENIED",
           mapping=replace(MAPPING,**{field:value}))

@pytest.mark.parametrize("field,value",[
    ("tenant_id",TENANT+1),
    ("branch_id",BRANCH+1),
])
def test_wrong_merchant_product_scope_denied(field,value):
    denied("PK_CROSS_TENANT_BRANCH_SKU_DENIED",
           product=replace(PRODUCT,**{field:value}))

@pytest.mark.parametrize("field,value",[
    ("state","DISABLED"),
    ("issuer_epoch",9),
    ("certified_axes",frozenset(("architecture",))),
])
def test_revoked_stale_or_incomplete_pack_denied(field,value):
    denied("PK_PACK_NOT_CURRENT_OR_REVOKED",
           pack=replace(PACK,**{field:value}))

def test_unmet_monotonic_issuer_floor_denied():
    denied("PK_PACK_NOT_CURRENT_OR_REVOKED",minimum_issuer_epoch=11)

def test_missing_synthetic_pack_disallows_ready_preview():
    denied("PK_SOURCE_TYPE_MISSING",pack=None)

@pytest.mark.parametrize("field,value",[
    ("category_code","OTHER"),
    ("family","kitchen"),
    ("unit_code","CARTON"),
    ("stock_tracked",False),
])
def test_classification_and_stock_policy_mismatch_denied(field,value):
    denied("PK_CLASSIFICATION_OR_STOCK_POLICY_DRIFT",
           product=replace(PRODUCT,**{field:value}))

def test_expired_tax_account_policy_denied():
    denied("PK_TAX_ACCOUNT_MAPPING_NOT_EFFECTIVE",
           mapping=replace(MAPPING,valid_until=NOW-timedelta(seconds=1)))

def test_future_tax_account_policy_denied():
    denied("PK_TAX_ACCOUNT_MAPPING_NOT_EFFECTIVE",
           mapping=replace(MAPPING,valid_from=NOW+timedelta(days=1)))

@pytest.mark.parametrize("field,value,code",[
    ("tax_policy_code","", "PK_TAX_REVENUE_MAPPING_MISSING"),
    ("tax_policy_revision",0,"PK_TAX_REVENUE_MAPPING_MISSING"),
    ("revenue_account_code","", "PK_TAX_REVENUE_MAPPING_MISSING"),
    ("inventory_account_code",None,"PK_STOCK_ACCOUNT_POLICY_CONFLICT"),
    ("cogs_account_code",None,"PK_STOCK_ACCOUNT_POLICY_CONFLICT"),
    ("uom_precision",7,"PK_UOM_PC3_POLICY_UNRATIFIED"),
    ("uom_precision",8,"PK_UOM_PC3_POLICY_UNRATIFIED"),
    ("pc3_policy_revision",0,"PK_UOM_PC3_POLICY_UNRATIFIED"),
    ("pc3_concept_sha256","changed","PK_UOM_PC3_POLICY_UNRATIFIED"),
])
def test_unratified_tax_account_or_classification_rejected(field,value,code):
    with pytest.raises(PKConfigDenied) as exc:
        replace(MAPPING,**{field:value})
    assert exc.value.code==code

def test_nonstock_service_can_have_no_inventory_account():
    mapping=replace(MAPPING,stock_tracked=False,inventory_account_code=None,cogs_account_code=None)
    product=replace(PRODUCT,stock_tracked=False)
    assert review(mapping=mapping,product=product).published is False

def test_nonstock_with_cogs_account_is_inconsistent():
    with pytest.raises(PKConfigDenied) as e:
        replace(MAPPING,stock_tracked=False,inventory_account_code=None)
    assert e.value.code=="PK_STOCK_ACCOUNT_POLICY_CONFLICT"

def test_unknown_nine_axes_cannot_replace_the_real_nine():
    with pytest.raises(PKConfigDenied) as e:
        replace(PACK,certified_axes=frozenset("unknown-"+str(i) for i in range(9)))
    assert e.value.code=="PK_PACK_READBACK_INVALID"

def test_untracked_with_stock_account_is_inconsistent():
    with pytest.raises(PKConfigDenied) as e:
        replace(MAPPING,stock_tracked=False)
    assert e.value.code=="PK_STOCK_ACCOUNT_POLICY_CONFLICT"

@pytest.mark.parametrize("expected", [3,5,True])
def test_stale_product_revision_denied(expected):
    denied("PK_STALE_PRODUCT_REVISION",expected_product_revision=expected)

@pytest.mark.parametrize("revs", [
    (2,4,1),(1,3,1),(2,3,9),
])
def test_each_independent_zone_revision_cas_denies_stale(revs):
    denied("PK_STALE_PRICE_REVISION",expected_price_revisions=revs)

@pytest.mark.parametrize("revs", [
    (), (2,1), (2,3,0), (2,True,1),
])
def test_missing_or_forged_zone_revision_denied(revs):
    denied("PK_PRICE_VERSION_FLOOR_MISSING",expected_price_revisions=revs)

@pytest.mark.parametrize("name,value",[
    ("tenant_id",TENANT+1),
    ("branch_id",BRANCH+1),
    ("sku","OTHER-SKU"),
])
def test_foreign_source_zone_quote_denied(name,value):
    prices=list(PRICES)
    prices[1]=replace(prices[1],**{name:value})
    denied("PK_PRICE_CROSS_SCOPE",current_prices=tuple(prices))

@pytest.mark.parametrize("revised",[
    (1700,2300,1700), (1700,2400,1900), (2700,2300,1900),
])
def test_client_quote_changes_cannot_override_sof_readback(revised):
    denied("PK_CLIENT_PRICE_OVERRIDE_OR_DRIFT",
           product=replace(PRODUCT,desired_price_amounts=revised))

@pytest.mark.parametrize("prices",[
    (), PRICES[:1], PRICES[:2],
])
def test_three_zone_sources_required(prices):
    denied("PK_THREE_ZONE_PRICE_PROOF_MISSING",current_prices=prices)

def test_duplicate_main_in_place_of_vip_denied():
    denied("PK_DUPLICATE_OR_MISSING_PRICE_ZONE",
           current_prices=(PRICES[0],replace(PRICES[1],zone="MAIN",price_code="retail"),PRICES[2]))

@pytest.mark.parametrize("field,value,code",[
    ("price_code","retail","PK_ZONE_PRICE_INVALID"),
    ("price_revision",0,"PK_ZONE_PRICE_INVALID"),
    ("amount_xaf",-1,"PK_ZONE_PRICE_INVALID"),
    ("amount_xaf",1900.5,"PK_ZONE_PRICE_INVALID"),
    ("price_row_sha256","INVALID","PK_ZONE_PRICE_INVALID"),
    ("authoritative_sof_verified",True,"PK_FORGED_PRICE_AUTHORITY"),
])
def test_price_row_cannot_be_forged(field,value,code):
    with pytest.raises(PKConfigDenied) as exc:
        replace(PRICES[2],**{field:value})
    assert exc.value.code==code

@pytest.mark.parametrize("field,value",[
    ("actual_signature_verified",True),
    ("effective_permission",True),
    ("source_grade","REAL_AUTHORITY"),
])
def test_synthetic_pack_cannot_mint_real_certification(field,value):
    with pytest.raises(PKConfigDenied) as exc:
        replace(PACK,**{field:value})
    assert exc.value.code=="PK_FORGED_PACK_AUTHORITY"

def test_synthetic_actor_cannot_claim_pc5():
    with pytest.raises(PKConfigDenied) as exc:
        replace(CTX,pc5_authenticated=True)
    assert exc.value.code=="PK_REAL_PC5_NOT_CLAIMABLE"

def test_synthetic_pc3_sof_source_cannot_claim_human_authority():
    with pytest.raises(PKConfigDenied) as exc:
        replace(MAPPING,owner_approved_real=True)
    assert exc.value.code=="PK_FORGED_SOF_PC3_AUTHORITY"

def test_bounded_scope_is_test_tenant_not_real_wnd():
    assert CTX.tenant_id==920002 and CTX.tenant_id!=2
    assert PACK.source_grade==GRADE
    assert not review().provider_paid

def test_price_revision_change_alters_digest_without_any_write():
    prices=list(PRICES)
    prices[1]=replace(prices[1],price_revision=4)
    p=review(current_prices=tuple(prices),
             expected_price_revisions=(2,4,1))
    assert p.digest_sha256!=review().digest_sha256
    assert p.published is False
