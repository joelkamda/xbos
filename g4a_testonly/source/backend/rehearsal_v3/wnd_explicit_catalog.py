"""WND V3 TEST-only explicit Main/VIP/Bar product and price intake.

This pure contract never opens WND data or a database. All values originate
in *invented nonpersonal TEST input*, never a WND backup, original price row,
or inferred multiplier. It can drive an isolated REAL PostgreSQL TEST
transaction when N/FE integrate the opt-in API route. Not genuine PC5 or
release authority.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from fastapi import HTTPException

ZONE_ORDER=("MAIN","VIP","BAR")
SOURCE_GRADE="SYNTHETIC_NONPERSONAL_TEST_ONLY"

class WndExplicitProduct(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_grade: Literal["SYNTHETIC_NONPERSONAL_TEST_ONLY"]
    name: str = Field(min_length=2,max_length=90)
    category: str | None = Field(default=None,max_length=50)
    family: Literal["bar","kitchen","other"] | None = None
    unit_code: str | None = Field(default=None,max_length=40)
    unit_precision: StrictInt | None = None
    tax_code: str | None = Field(default=None,max_length=40)
    revenue_account: str | None = Field(default=None,max_length=80)
    stock_tracked: StrictBool | None = None
    service: StrictBool | None = None
    stock_qty: StrictInt | None = None
    zone_prices: dict[Literal["MAIN","VIP","BAR"],StrictInt] | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls,value:str)->str:
        value=value.strip()
        if len(value)<2:
            raise ValueError("W_TEST_NAME_REQUIRED")
        return value

class WndPriceDenied(HTTPException):
    def __init__(self, reason:str, status_code:int=422):
        super().__init__(status_code=status_code,detail=reason)

def review(body:WndExplicitProduct)->dict:
    """No writes. Unspecified fields remain a DRAFT, not an inferred value."""
    missing=[]
    for field in ("category","family","unit_code","unit_precision",
                  "tax_code","revenue_account","stock_tracked","service",
                  "zone_prices"):
        if getattr(body,field) is None or getattr(body,field)=="":
            missing.append(field)
    if body.unit_precision is not None and not 0<=body.unit_precision<=6:
        missing.append("unit_precision")
    if body.stock_qty is not None and not 0<=body.stock_qty<=100000:
        raise WndPriceDenied("W_TEST_INVALID_STOCK_QUANTITY")
    if body.stock_tracked is True and body.service is True:
        raise WndPriceDenied("W_D7_CATALOG_SERVICE_STOCK_CONFLICT")
    if body.stock_tracked is True and body.stock_qty is None:
        missing.append("stock_qty")
    if body.stock_tracked is False and body.stock_qty is not None:
        raise WndPriceDenied("W_TEST_NONSTOCK_CANNOT_HAVE_QUANTITY")
    if body.service is True and body.family=="bar":
        raise WndPriceDenied("W_TEST_BAR_SERVICE_CATEGORY_CONFLICT")
    prices=body.zone_prices
    if prices is not None:
        if set(prices)!=set(ZONE_ORDER):
            missing.append("exact_three_zone_prices")
        for value in prices.values():
            if value<=0 or value>500000:
                raise WndPriceDenied("W_TEST_ZONE_AMOUNT_INVALID")
    # Deliberately no default from MAIN to VIP/BAR, no source WND fingerprint.
    price_rows=(
       [{"zone":z,"price_code":{"MAIN":"retail","VIP":"vip_lounge",
          "BAR":"bar_premium"}[z],"amount_xaf":prices[z],"price_revision":1,
          "source":"EXPLICIT_SYNTHETIC_TEST_VALUE"}
        for z in ZONE_ORDER] if prices and set(prices)==set(ZONE_ORDER) else []
    )
    missing=sorted(set(missing))
    return {
        "disposition":"READY_FOR_ISOLATED_TEST_ACTIVATION" if not missing else "DRAFT_NEEDS_CLASSIFICATION",
        "missing":missing,"sourceGrade":SOURCE_GRADE,
        "sourceOnly":True,"ready":not missing,
        "priceRows":price_rows,"zoneCount":len(price_rows),
        "serverDerivedMultipliers":False,"realWndPriceRows":0,
        "genuinePc5":False,"g3Admitted":False,"g4Released":False,
        "published":False,"stockEffects":0,"financeEffects":0,
        "printerEffects":0,"paymentEffects":0
    }

def require_activation(body:WndExplicitProduct)->dict:
    result=review(body)
    if not result["ready"]:
        raise WndPriceDenied("W_TEST_PRODUCT_DRAFT_INCOMPLETE",409)
    return result
