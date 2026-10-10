"""N2 bounded, zero-database golden comparison.

These tests verify extracted policy values but DO NOT attest runtime binding
or current WND tenant policy activation. Those require explicit authority.
"""
from __future__ import annotations

import unittest

from core.api.orders.orders_controller import OrdersController
from core.domain.inventory.service import InventoryService
from core.domain.inventory.taxonomy_profile import (
    _name_suggests_family as legacy_name_family,
    _subcategory_score as legacy_subcategory_score,
    _category_family as legacy_category_family,
)
from core.domain.operational_policy import NEUTRAL_POLICY, OperationalPolicy
from restaurant.r4.wnd_operational_policy import WND_POLICY


class N2PolicyGoldenTests(unittest.TestCase):
    def test_wnd_implements_neutral_contract(self):
        self.assertIsInstance(WND_POLICY, OperationalPolicy)  # structural Protocol

    def test_wnd_order_golden_parity(self):
        class Controller(OrdersController):
            def __init__(self, names, category, subcategory):
                self.names, self.category, self.subcategory = names, category, subcategory
            def _taxonomy_path_for_atomic_unit(self, *_args, **_kwargs):
                return {"names": self.names, "category": self.category, "subcategory": self.subcategory}
        cases = (
            (["Inventory", "MAIN DISH", "SAUCE"], "MAIN DISH", "SAUCE", None),
            (["Inventory", "BEER"], "BEER", None, "waiting"),
            (["Inventory", "MAIN DISH", "BEER"], "MAIN DISH", "BEER", "ready"),
            (["Inventory", "HOT DRINKS"], "HOT DRINKS", "", "fulfilled"),
            (["Inventory", "UNKNOWN"], "UNKNOWN", None, "waiting"),
            (["Inventory", "DESSERT"], "DESSERT", None, None),
        )
        for names, category, subcategory, status in cases:
            with self.subTest(names=names, status=status):
                legacy = Controller(names, category, subcategory)._fulfillment_payload_for_item(
                    None, tenant_id=2, atomic_unit_id=1, stored_status=status,
                )
                normalized = str(status or "waiting").strip().lower()
                policy = WND_POLICY.fulfillment(
                    {n.strip().upper() for n in names}, str(category or "").strip().upper(),
                    str(subcategory or "").strip().upper(), normalized,
                )
                self.assertEqual(
                    legacy,
                    {**policy, "commerce_category": category, "commerce_subcategory": subcategory},
                )

    def test_wnd_inventory_alias_and_taxonomy_parity(self):
        for name in ("towel", "Ndole", "White Beans", "RED BULL", "Castel", "Unknown Gadget", "Poulet"):
            with self.subTest(name=name):
                self.assertEqual(WND_POLICY.name_family(name), legacy_name_family(name))
        for name in ("White Beans", "RED BULL", "towel", "Moët", "Unknown"):
            for category in ("Main Dish", "Breakfast", "Wine", "Beer", "Soft Drinks", "Whiskey", None):
                with self.subTest(name=name, category=category):
                    self.assertEqual(WND_POLICY.subcategory_score(name, category),
                                     legacy_subcategory_score(name, category))
        for category in ("food", "drinks", "others", "unknown", None):
            self.assertEqual(WND_POLICY.category_family(category), legacy_category_family(category))

    def test_wnd_negative_stock_parity(self):
        for family in ("kitchen", "bar", "other", "non_inventory", ""):
            self.assertEqual(
                WND_POLICY.negative_stock(family),
                InventoryService.allow_negative_from_profile({"inventory_family": family}),
            )
        for explicit in (True, False):
            for family in ("kitchen", "bar", "other"):
                # Explicit profile policy remains authoritative.
                self.assertEqual(
                    InventoryService.allow_negative_from_profile({
                        "inventory_family": family,
                        "allow_negative_stock": explicit,
                    }),
                    explicit,
                )

    def test_unrelated_tenant_neutrality_and_no_policy_denial(self):
        self.assertIsNone(NEUTRAL_POLICY.name_family("towel"))
        self.assertIsNone(NEUTRAL_POLICY.name_family("Beer"))
        self.assertIsNone(NEUTRAL_POLICY.category_family("food"))
        self.assertEqual(NEUTRAL_POLICY.subcategory_score("towel", "MAIN DISH"), 0)
        self.assertFalse(NEUTRAL_POLICY.negative_stock("kitchen"))
        self.assertFalse(NEUTRAL_POLICY.negative_stock("bar"))
        self.assertFalse(NEUTRAL_POLICY.negative_stock(""))
        result = NEUTRAL_POLICY.fulfillment({"MAIN DISH"}, "MAIN DISH", "KITCHEN", "waiting")
        self.assertFalse(result["requires_preparation"])
        self.assertFalse(result["requires_fulfillment"])
        self.assertIsNone(result["fulfillment_queue"])
        self.assertIsNone(result["fulfillment_station"])


if __name__ == "__main__":
    unittest.main()
