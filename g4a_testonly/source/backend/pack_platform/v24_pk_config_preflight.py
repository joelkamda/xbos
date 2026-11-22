"""V24 PK D7-08/09 synthetic-only product configuration preflight.

Authoritative facts remain owned by N/PC3 taxonomy, SOF tax/accounts/prices,
PA genuine PC5, and PK certified pack registry. These immutable projections
are DATA asserted by synthetic fixtures, not credentials/registry/SQL access.
Returns an intentionally NONOPERATIVE review receipt, never permission, sale,
installation, official Finance posting, publication or PSP finality.

Price version checking is a compatibility check only; actual publication
MUST perform an atomic DB row-version compare under transaction lock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import re

DIGEST = re.compile(r"^[0-9a-f]{64}$")
ZONES = ("MAIN", "VIP", "BAR")
CODES = {"MAIN":"retail","VIP":"vip_lounge","BAR":"bar_premium"}
GRADE = "SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED"
NINE_AXES = frozenset((
    "architecture", "tenant_isolation", "migration_compatibility",
    "authorization", "semantics", "finance", "shared_operations",
    "xa", "manifest",
))


class PKConfigDenied(ValueError):
    def __init__(self, code: str):
        self.code=code
        super().__init__(code)


def require(ok: bool, code: str) -> None:
    if ok is not True:
        raise PKConfigDenied(code)


def positive(n: int) -> bool:
    return type(n) is int and n > 0


def token(x: str) -> bool:
    return type(x) is str and bool(x.strip())


def sha(x: str) -> bool:
    return type(x) is str and DIGEST.fullmatch(x) is not None


@dataclass(frozen=True)
class TenantContext:
    tenant_id: int
    branch_id: int
    actor_ref: str
    source_only: bool = True
    pc5_authenticated: bool = False

    def __post_init__(self):
        require(positive(self.tenant_id) and positive(self.branch_id)
                and token(self.actor_ref), "PK_TENANT_SCOPE_INVALID")
        require(self.source_only is True
                and self.pc5_authenticated is False,
                "PK_REAL_PC5_NOT_CLAIMABLE")


@dataclass(frozen=True)
class PackReadback:
    tenant_id: int
    branch_id: int
    pack_code: str
    version: str
    manifest_sha256: str
    cert_sha256: str
    version_revision: int
    issuer_epoch: int
    certified_axes: frozenset[str]
    state: str
    source_grade: str = GRADE
    effective_permission: bool = False
    actual_signature_verified: bool = False

    def __post_init__(self):
        require(positive(self.tenant_id) and positive(self.branch_id)
                and self.pack_code=="industry.restaurant"
                and token(self.version)
                and sha(self.manifest_sha256)
                and sha(self.cert_sha256)
                and positive(self.version_revision)
                and positive(self.issuer_epoch)
                and type(self.certified_axes) is frozenset
                and self.certified_axes.issubset(NINE_AXES),
                "PK_PACK_READBACK_INVALID")
        require(self.source_grade==GRADE
                and self.effective_permission is False
                and self.actual_signature_verified is False,
                "PK_FORGED_PACK_AUTHORITY")


@dataclass(frozen=True)
class CanonicalMapping:
    """PC3/SOF owner-assigned code references, supplied only as TEST fixtures."""
    tenant_id: int
    branch_id: int
    sku: str
    category_code: str
    family: str
    unit_code: str
    uom_precision: int
    pc3_policy_revision: int
    pc3_concept_sha256: str
    tax_policy_code: str
    tax_policy_revision: int
    revenue_account_code: str
    inventory_account_code: str | None
    cogs_account_code: str | None
    stock_tracked: bool
    valid_from: datetime
    valid_until: datetime | None
    source_grade: str = GRADE
    owner_approved_real: bool = False

    def __post_init__(self):
        require(positive(self.tenant_id) and positive(self.branch_id)
                and token(self.sku) and token(self.category_code)
                and self.family in ("bar","kitchen","other")
                and token(self.unit_code), "PK_CLASSIFICATION_INVALID")
        require(type(self.uom_precision) is int
                and 0 <= self.uom_precision <= 6
                and positive(self.pc3_policy_revision)
                and sha(self.pc3_concept_sha256),
                "PK_UOM_PC3_POLICY_UNRATIFIED")
        require(token(self.tax_policy_code)
                and positive(self.tax_policy_revision)
                and token(self.revenue_account_code),
                "PK_TAX_REVENUE_MAPPING_MISSING")
        require(type(self.stock_tracked) is bool
                and (self.stock_tracked is False
                     or (token(self.inventory_account_code)
                         and token(self.cogs_account_code)))
                and (self.stock_tracked is True
                     or (self.inventory_account_code is None
                         and self.cogs_account_code is None)),
                "PK_STOCK_ACCOUNT_POLICY_CONFLICT")
        require(isinstance(self.valid_from,datetime)
                and self.valid_from.tzinfo is not None
                and self.valid_from.utcoffset() is not None
                and (self.valid_until is None
                     or (isinstance(self.valid_until,datetime)
                         and self.valid_until.tzinfo is not None
                         and self.valid_until.utcoffset() is not None
                         and self.valid_until > self.valid_from)),
                "PK_POLICY_TIME_INVALID")
        require(self.source_grade==GRADE
                and self.owner_approved_real is False,
                "PK_FORGED_SOF_PC3_AUTHORITY")


@dataclass(frozen=True)
class MerchantProduct:
    tenant_id: int
    branch_id: int
    sku: str
    category_code: str
    family: str
    unit_code: str
    draft_revision: int
    desired_price_amounts: tuple[int, int, int]
    stock_tracked: bool

    def __post_init__(self):
        require(positive(self.tenant_id)
                and positive(self.branch_id) and token(self.sku)
                and positive(self.draft_revision)
                and type(self.desired_price_amounts) is tuple
                and len(self.desired_price_amounts)==3
                and all(type(n) is int and n>=0
                        for n in self.desired_price_amounts),
                "PK_MERCHANT_PRODUCT_INPUT_INVALID")


@dataclass(frozen=True)
class ZonePriceReadback:
    tenant_id: int
    branch_id: int
    sku: str
    zone: str
    price_code: str
    amount_xaf: int
    price_revision: int
    price_row_sha256: str
    source_only: bool = True
    authoritative_sof_verified: bool = False

    def __post_init__(self):
        require(positive(self.tenant_id) and positive(self.branch_id)
                and token(self.sku)
                and self.zone in ZONES
                and self.price_code==CODES[self.zone]
                and type(self.amount_xaf) is int
                and self.amount_xaf>=0
                and positive(self.price_revision)
                and sha(self.price_row_sha256),
                "PK_ZONE_PRICE_INVALID")
        require(self.source_only is True
                and self.authoritative_sof_verified is False,
                "PK_FORGED_PRICE_AUTHORITY")


@dataclass(frozen=True)
class Preflight:
    tenant_id: int
    branch_id: int
    sku: str
    draft_revision: int
    zones: tuple[str,...]
    digest_sha256: str
    status: str = "TEST_SOURCE_REVIEW_ELIGIBLE_NOT_AUTHORIZED"
    effective_permission: bool = False
    pc5_admitted: bool = False
    pack_certified_real: bool = False
    can_publish: bool = False
    published: bool = False
    posted_finance: bool = False
    provider_paid: bool = False

    def __post_init__(self):
        require(sha(self.digest_sha256)
                and self.status=="TEST_SOURCE_REVIEW_ELIGIBLE_NOT_AUTHORIZED"
                and all(getattr(self,k) is False for k in (
                    "effective_permission","pc5_admitted","pack_certified_real",
                    "can_publish","published","posted_finance","provider_paid")),
                "PK_PREVIEW_PRIVILEGE_ESCALATION_DENIED")


def preview_pack_tax_account_and_price_cas(
    *, context:TenantContext, pack:PackReadback,
    mapping:CanonicalMapping, product:MerchantProduct,
    current_prices:tuple[ZonePriceReadback,...],
    expected_product_revision:int,
    expected_price_revisions:tuple[int,int,int],
    minimum_issuer_epoch:int, at:datetime,
)->Preflight:
    """Fail closed on synthetic source mismatch. Not real publication authority."""
    require(all(type(x) is y for x,y in (
        (context,TenantContext),(pack,PackReadback),(mapping,CanonicalMapping),
        (product,MerchantProduct))), "PK_SOURCE_TYPE_MISSING")
    require(type(at) is datetime and at.tzinfo is not None
            and at.utcoffset() is not None, "PK_ASOF_REQUIRED")
    require((context.tenant_id,context.branch_id)
            ==(pack.tenant_id,pack.branch_id)
            ==(mapping.tenant_id,mapping.branch_id)
            ==(product.tenant_id,product.branch_id)
            and mapping.sku==product.sku,
            "PK_CROSS_TENANT_BRANCH_SKU_DENIED")
    require(pack.state=="ACTIVE_SOURCE" and pack.certified_axes==NINE_AXES
            and positive(minimum_issuer_epoch)
            and pack.issuer_epoch>=minimum_issuer_epoch,
            "PK_PACK_NOT_CURRENT_OR_REVOKED")
    require((mapping.category_code,mapping.family,mapping.unit_code,
             mapping.stock_tracked)
            ==(product.category_code,product.family,product.unit_code,
               product.stock_tracked),
            "PK_CLASSIFICATION_OR_STOCK_POLICY_DRIFT")
    require(mapping.valid_from<=at
            and (mapping.valid_until is None or at<mapping.valid_until),
            "PK_TAX_ACCOUNT_MAPPING_NOT_EFFECTIVE")
    require(type(expected_product_revision) is int
            and expected_product_revision==product.draft_revision,
            "PK_STALE_PRODUCT_REVISION")
    require(type(expected_price_revisions) is tuple
            and len(expected_price_revisions)==3
            and all(positive(v) for v in expected_price_revisions),
            "PK_PRICE_VERSION_FLOOR_MISSING")
    require(type(current_prices) is tuple
            and len(current_prices)==3
            and all(type(p) is ZonePriceReadback for p in current_prices),
            "PK_THREE_ZONE_PRICE_PROOF_MISSING")
    zones={p.zone:p for p in current_prices}
    require(len(zones)==3 and set(zones)==set(ZONES),
            "PK_DUPLICATE_OR_MISSING_PRICE_ZONE")
    for i,zone in enumerate(ZONES):
        p=zones[zone]
        require((p.tenant_id,p.branch_id,p.sku)
                ==(context.tenant_id,context.branch_id,product.sku),
                "PK_PRICE_CROSS_SCOPE")
        require(p.price_revision==expected_price_revisions[i],
                "PK_STALE_PRICE_REVISION")
        require(p.amount_xaf==product.desired_price_amounts[i],
                "PK_CLIENT_PRICE_OVERRIDE_OR_DRIFT")
    raw="|".join([
        str(context.tenant_id),str(context.branch_id),product.sku,
        str(product.draft_revision),pack.version,pack.cert_sha256,
        str(pack.issuer_epoch),mapping.pc3_concept_sha256,
        str(mapping.pc3_policy_revision),mapping.tax_policy_code,
        str(mapping.tax_policy_revision),mapping.revenue_account_code,
        mapping.inventory_account_code or "NONE",
        mapping.cogs_account_code or "NONE",
        *(f"{z}:{zones[z].price_code}:{zones[z].amount_xaf}:"
          f"{zones[z].price_revision}:{zones[z].price_row_sha256}"
          for z in ZONES),
    ])
    return Preflight(context.tenant_id,context.branch_id,product.sku,
                     product.draft_revision,ZONES,
                     sha256(raw.encode("utf-8")).hexdigest())
