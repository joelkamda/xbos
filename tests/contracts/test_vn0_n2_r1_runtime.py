"""N2-R1 exact before/after shared and compatibility runtime goldens."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as O
from unittest.mock import patch

from core.api.orders.orders_controller import OrdersController as GenericOrders
from restaurant.r6.wnd_api_compat.orders_controller import OrdersController as CompatOrders
from restaurant.r6.wnd_api_compat.inventory_service import InventoryService as CompatInventory
from core.domain.inventory import taxonomy_profile as taxonomy
from core.domain.inventory.service import InventoryService as GenericInventory
from core.domain.operational_policy import NEUTRAL_POLICY
from restaurant.wnd_operational_policy import WND_POLICY

GOLDENS = json.loads((Path(__file__).parent/"vn0_n2_r1_preextraction_goldens.json").read_text())

class N2R1RuntimeParity(unittest.TestCase):
    @staticmethod
    def node(id, name, level, parent=None):
        return O(id=id, name=name, semantic_level=level, parent_id=parent, sort_order=id)

    def setUp(self):
        node=self.node
        self.nodes = {1:node(1,"Inventory","domain"),2:node(2,"Food","category",1),
            3:node(3,"Drinks","category",1),4:node(4,"Others","category",1),
            5:node(5,"Main Dish","subcategory",2),6:node(6,"Wine","subcategory",3),
            7:node(7,"Beer","subcategory",3),8:node(8,"Soft Drinks","subcategory",3)}

    def inventory(self, case, policy):
        unit=O(id=13, name=case["name"], meta=case["meta"])
        with patch.object(taxonomy,"_load_atomic_unit",return_value=unit),\
             patch.object(taxonomy,"_load_commerce_nodes",return_value=self.nodes),\
             patch.object(taxonomy,"_load_unit_commerce_mapping_nodes",return_value=[self.nodes[i] for i in case["mappings"]]):
            return taxonomy.resolve_inventory_profile(None,tenant_id=2,atomic_unit_id=13,policy=policy)

    def test_wnd_full_inventory_golden(self):
        for case in GOLDENS["inventory_cases"]:
            with self.subTest(case=case["name"]):
                actual=self.inventory(case,WND_POLICY)
                expected={**case["expected"],"atomic_unit_id":13}
                self.assertEqual(actual,expected)

    def test_r6_inventory_consumes_authoritative_policy(self):
        case=GOLDENS["inventory_cases"][0]
        unit=O(id=1, name=case["name"], meta=case["meta"])
        with patch.object(taxonomy,"_load_atomic_unit",return_value=unit),\
             patch.object(taxonomy,"_load_commerce_nodes",return_value=self.nodes),\
             patch.object(taxonomy,"_load_unit_commerce_mapping_nodes",return_value=[self.nodes[i] for i in case["mappings"]]),\
             patch("restaurant.r6.wnd_api_compat.inventory_service.resolve_for_tenant",return_value=WND_POLICY) as selector:
            actual=CompatInventory.get_inventory_profile(None,tenant_id=2,atomic_unit_id=1)
            self.assertEqual(actual,case["expected"])
            selector.assert_called_once_with(None,2)

    def test_no_policy_is_neutral_even_with_restaurant_taxonomy(self):
        case=GOLDENS["inventory_cases"][0]
        neutral=self.inventory(case,NEUTRAL_POLICY)
        self.assertNotEqual(neutral["inventory_family"],"kitchen")
        self.assertFalse(neutral["allow_negative_stock"])
        self.assertFalse(GenericInventory.allow_negative_from_profile({"inventory_family":"kitchen"}))
        self.assertFalse(GenericInventory.allow_negative_from_profile(None))
        self.assertTrue(GenericInventory.allow_negative_from_profile({"allow_negative_stock":True}))

    def test_order_golden_for_generic_injected_policy_and_r6(self):
        class Generic(GenericOrders):
            def _taxonomy_path_for_atomic_unit(self,*a,**kw):return self.path
        class Compat(CompatOrders):
            def _taxonomy_path_for_atomic_unit(self,*a,**kw):return self.path
        for case in GOLDENS["order_cases"]:
            with self.subTest(case=case["names"]):
                path={"names":case["names"],"category":case["category"],"subcategory":case["subcategory"]}
                controller=Generic(policy=WND_POLICY); controller.path=path
                out=controller._fulfillment_payload_for_item(None,tenant_id=2,atomic_unit_id=1,stored_status=case["status"])
                self.assertEqual(out,case["expected"])
                compat=Compat();compat.path=path
                with patch("restaurant.r6.wnd_api_compat.orders_controller.resolve_for_tenant",return_value=WND_POLICY) as resolver:
                    output=compat._fulfillment_payload_for_item(None,tenant_id=2,atomic_unit_id=1,stored_status=case["status"])
                    resolver.assert_called_once_with(None,2)
                    self.assertEqual(output,case["expected"])
                neutral=Generic(policy=NEUTRAL_POLICY);neutral.path=path
                safe=neutral._fulfillment_payload_for_item(None,tenant_id=3,atomic_unit_id=1,stored_status=case["status"])
                self.assertFalse(safe["requires_preparation"])
                self.assertIsNone(safe["fulfillment_queue"])

    def test_generic_order_without_policy_defaults_neutral(self):
        instance=GenericOrders()
        self.assertIs(instance.operational_policy,NEUTRAL_POLICY)

if __name__=="__main__":
    unittest.main()
