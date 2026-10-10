"""N2-R1: WND order writes pass the same selected policy into reservations."""
import asyncio
import unittest
from types import SimpleNamespace as O
from unittest.mock import patch

from core.domain.operational_policy import NEUTRAL_POLICY
from core.domain.inventory.service import InventoryService
from core.api.orders.orders_controller import OrdersController as GenericOrders
from restaurant.r6.wnd_api_compat.orders_controller import OrdersController as CompatOrders
from restaurant.wnd_operational_policy import WND_POLICY

class WritePolicyPropagation(unittest.TestCase):
    def test_r6_order_create_passes_selected_policy(self):
        req=O(state=O(user={"tenant_id":2,"branch_id":1,"user_id":3,"role":"cashier"}))
        controller=CompatOrders()
        obj=O(id=101)
        with patch("restaurant.r6.wnd_api_compat.orders_controller.resolve_for_tenant",return_value=WND_POLICY) as resolver,\
             patch("restaurant.r6.wnd_api_compat.orders_controller.OrderService.create_order",return_value=obj) as service,\
             patch("restaurant.r6.wnd_api_compat.orders_controller.OrderRepository.get_by_id",return_value=obj),\
             patch.object(CompatOrders,"_serialize_order",return_value={"id":101}):
            result=asyncio.run(controller.create_order(req,{"items":[1]},None))
            self.assertEqual(result["id"],101)
            self.assertIs(service.call_args.kwargs["policy"],WND_POLICY)
            resolver.assert_called_once_with(None,2)

    def test_r6_order_update_passes_selected_policy(self):
        req=O(state=O(user={"tenant_id":2,"branch_id":1,"user_id":3,"role":"cashier"}))
        controller=CompatOrders()
        obj=O(id=101)
        with patch("restaurant.r6.wnd_api_compat.orders_controller.resolve_for_tenant",return_value=WND_POLICY) as resolver,\
             patch("restaurant.r6.wnd_api_compat.orders_controller.OrderService.update_order",return_value=obj) as service,\
             patch("restaurant.r6.wnd_api_compat.orders_controller.OrderRepository.get_by_id",return_value=obj),\
             patch.object(CompatOrders,"_serialize_order",return_value={"id":101}):
            result=asyncio.run(controller.update_order(req,101,{"items":[1]},None))
            self.assertEqual(result["message"],"Order updated successfully")
            self.assertIs(service.call_args.kwargs["policy"],WND_POLICY)
            resolver.assert_called_once_with(None,2)

    def test_generic_order_create_has_neutral_policy(self):
        req=O(state=O(user={"tenant_id":4,"branch_id":1,"user_id":3,"role":"cashier"}))
        controller=GenericOrders()
        obj=O(id=200)
        with patch("core.api.orders.orders_controller.OrderService.create_order",return_value=obj) as service,\
             patch("core.api.orders.orders_controller.OrderRepository.get_by_id",return_value=obj),\
             patch.object(GenericOrders,"_serialize_order",return_value={"id":200}):
            result=asyncio.run(controller.create_order(req,{"items":[1]},None))
            self.assertEqual(result,{"id":200})
            self.assertIs(service.call_args.kwargs["policy"],NEUTRAL_POLICY)

    def test_reservation_and_adjustment_require_explicit_policy(self):
        order=O(id=101,tenant_id=2,branch_id=1,items=[O(atomic_unit_id=12,quantity=1)])
        with patch.object(InventoryService,"get_inventory_profile",return_value={"stock_tracked":False,"allow_negative_stock":True}) as get:
            result=InventoryService.reserve_order_inventory(None,order=order,policy=WND_POLICY)
            self.assertEqual(result,[])
            self.assertIs(get.call_args.kwargs["policy"],WND_POLICY)
        with patch.object(InventoryService,"get_inventory_profile",return_value={"stock_tracked":False,"allow_negative_stock":True}) as get:
            result=InventoryService.adjust_order_reservation(None,order=order,
                old_items=[{"atomic_unit_id":12,"quantity":1}],new_items=[{"atomic_unit_id":12,"quantity":2}],
                policy=WND_POLICY)
            self.assertEqual(result,[])
            self.assertIs(get.call_args.kwargs["policy"],WND_POLICY)

    def test_absent_policy_on_reservation_is_neutral(self):
        order=O(id=201,tenant_id=4,branch_id=1,items=[O(atomic_unit_id=12,quantity=1)])
        with patch.object(InventoryService,"get_inventory_profile",return_value={"stock_tracked":False}) as get:
            InventoryService.reserve_order_inventory(None,order=order)
            self.assertIs(get.call_args.kwargs["policy"],NEUTRAL_POLICY)

if __name__=="__main__":
    unittest.main()
