"""N2 materialized policy goldens (immutable baseline captured before R1 wiring)."""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from core.domain.inventory.service import InventoryService
from core.domain.operational_policy import NEUTRAL_POLICY, OperationalPolicy
from restaurant.wnd_operational_policy import WND_POLICY

GOLDENS = json.loads((Path(__file__).parent/"vn0_n2_r1_preextraction_goldens.json").read_text())

class N2PolicyGoldenTests(unittest.TestCase):
    def test_wnd_implements_neutral_contract(self):
        self.assertIsInstance(WND_POLICY,OperationalPolicy)

    def test_wnd_order_golden_parity(self):
        for case in GOLDENS["order_cases"]:
            with self.subTest(names=case["names"]):
                status=str(case["status"] or "waiting").strip().lower()
                result=WND_POLICY.fulfillment(
                    {x.strip().upper() for x in case["names"]},
                    str(case["category"] or "").upper(),
                    str(case["subcategory"] or "").upper(),status)
                expected={k:v for k,v in case["expected"].items() if not k.startswith("commerce_")}
                self.assertEqual(result,expected)

    def test_wnd_inventory_alias_and_taxonomy_parity(self):
        self.assertEqual(WND_POLICY.name_family("towel"),"kitchen")
        self.assertEqual(WND_POLICY.name_family("RED BULL"),"bar")
        self.assertIsNone(WND_POLICY.name_family("Unknown Gadget"))
        self.assertEqual(WND_POLICY.subcategory_score("towel","Main Dish"),20)
        self.assertEqual(WND_POLICY.category_family("food"),"kitchen")
        self.assertEqual(WND_POLICY.category_family("drinks"),"bar")
        self.assertEqual(WND_POLICY.category_family("others"),"other")

    def test_wnd_negative_stock_parity(self):
        for family in ("kitchen","bar","other","non_inventory",""):
            with self.subTest(family=family):
                expected=family=="kitchen"
                self.assertEqual(WND_POLICY.negative_stock(family),expected)
                self.assertEqual(InventoryService.allow_negative_from_profile({
                    "inventory_family":family, "allow_negative_stock":expected}),expected)
        self.assertFalse(InventoryService.allow_negative_from_profile({"inventory_family":"kitchen"}))

    def test_unrelated_tenant_neutrality_and_no_policy_denial(self):
        self.assertIsNone(NEUTRAL_POLICY.name_family("towel"))
        self.assertIsNone(NEUTRAL_POLICY.category_family("food"))
        self.assertEqual(NEUTRAL_POLICY.subcategory_score("towel","Main Dish"),0)
        self.assertFalse(NEUTRAL_POLICY.negative_stock("kitchen"))
        result=NEUTRAL_POLICY.fulfillment({"MAIN DISH"},"MAIN DISH","KITCHEN","waiting")
        self.assertFalse(result["requires_preparation"])
        self.assertFalse(result["requires_fulfillment"])
        self.assertIsNone(result["fulfillment_queue"])
        self.assertIsNone(result["fulfillment_station"])

if __name__=="__main__":
    unittest.main()
