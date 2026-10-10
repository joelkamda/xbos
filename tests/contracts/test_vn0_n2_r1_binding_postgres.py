"""N2-R1 real PC4 + PK0123 binding, disposable local PostgreSQL only."""
import os
import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from core.tenants.tenant_model import Tenant
from core.users.user_model import User
from core.platform.operating_context import (
    ConfigScope, ConfigType, OperatingContextAuthority, SetConfiguration,
)
from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
from core.domain.operational_policy import NEUTRAL_POLICY
from pack_platform import PackAuthority
from pack_platform.contracts import RegisterPackVersion, StagePack, InstallPack, ActivatePack
from pack_platform.sql_repository import SQLPackRepository
from restaurant.r4 import build_restaurant_pack_manifest
from restaurant.wnd_operational_policy import WND_POLICY
from restaurant.operational_policy_binding import (
    OperationalPolicyBindingError, SELECTOR_KEY, define_selector,
    resolve_operational_policy, resolve_for_tenant,
)

URL=os.environ.get("N2_R1_TEST_DATABASE_URL","")
if URL:
    _url=make_url(URL)
    if _url.host not in ("127.0.0.1","localhost","::1") or _url.database!="xbos_n2_r1_acceptance":
        raise RuntimeError("N2_R1_DISPOSABLE_DATABASE_FIREWALL")

class N2R1BindingPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not URL:
            raise unittest.SkipTest("N2_R1_TEST_DATABASE_URL must point to disposable local PostgreSQL")
        cls.engine=create_engine(URL,pool_pre_ping=True)
        cls.connection=cls.engine.connect()
        cls.outer=cls.connection.begin()
        cls.db=Session(bind=cls.connection)
        cls.instant=datetime(2026,10,9,20,0,tzinfo=timezone.utc)
        cls.pk=PackAuthority(SQLPackRepository(cls.db))
        cls.pc4=OperatingContextAuthority(SQLOperatingContextRepository(cls.db))
        for tenant_id,name,code in (
            (2,"Independent Tenant Two","independent2"),
            (3,"Wine & Dine","wnd"),
            (4,"Another Restaurant","independent4"),
            (5,"Restaurant With Bad Profile","independent5"),
            (6,"No Pack Configured","independent6"),
        ):
            cls.db.add(Tenant(id=tenant_id,code=code,name=name,country_code="CM",
                              currency="XAF",locale="fr",timezone="Africa/Douala"))
        cls.db.flush()
        cls.pc4.define if False else None
        define_selector(cls.pc4)
        definition=cls.pc4.repository.definition(SELECTOR_KEY)
        cls.definition=definition
        cls.pack_record=cls.pk.register(RegisterPackVersion(
            "n2-r1-pack-registration",build_restaurant_pack_manifest(),
        ))
        cls.db.flush()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.outer.rollback()
        cls.connection.close()
        cls.engine.dispose()

    @classmethod
    def activate(cls,tenant_id):
        staged=cls.pk.stage(StagePack(f"n2-{tenant_id}-stage",tenant_id,"industry.restaurant","1.0.0"))
        installed=cls.pk.install(InstallPack(f"n2-{tenant_id}-install",tenant_id,
                  "industry.restaurant","1.0.0",staged.row_version))
        activated=cls.pk.activate(ActivatePack(f"n2-{tenant_id}-activate",tenant_id,
                  "industry.restaurant","1.0.0",installed.row_version))
        return activated

    @classmethod
    def set_profile(cls,tenant_id,value):
        return cls.pc4.set_value(SetConfiguration(
            f"n2-{tenant_id}-profile-{value}", tenant_id, SELECTOR_KEY,
            ConfigScope.TENANT,tenant_id,value,cls.instant,
        ))

    @classmethod
    def resolve(cls,tenant_id):
        return resolve_operational_policy(
            tenant_id=tenant_id,as_of=cls.instant,
            pack_authority=cls.pk,operating_context=cls.pc4,
        )

    def test_01_definition_pc4_contract(self):
        self.assertEqual(self.definition.owner_code,"restaurant")
        self.assertEqual(self.definition.value_type,ConfigType.CODE)
        self.assertEqual(self.definition.allowed_scopes,(ConfigScope.TENANT,))
        self.assertEqual(self.definition.resolution_order,(ConfigScope.TENANT,))
        self.assertIsNone(self.definition.default_value)
        self.assertFalse(self.definition.secret)
        self.assertFalse(self.definition.required)
        self.assertTrue(self.definition.tenant_overridable)
        self.assertEqual(self.pack_record.version,"1.0.0")

    def test_02_no_pack_no_profile_is_neutral_even_if_tenant_id_two_or_named_wnd(self):
        self.assertIs(self.resolve(2),NEUTRAL_POLICY)
        self.assertIs(self.resolve(3),NEUTRAL_POLICY)

    def test_03_active_pack_alone_is_neutral(self):
        self.activate(2)
        self.assertIs(self.resolve(2),NEUTRAL_POLICY)

    def test_04_active_pack_and_pc4_wnd_is_wnd(self):
        self.set_profile(2,"wnd.logpom")
        self.assertIs(self.resolve(2),WND_POLICY)
        self.assertIs(resolve_for_tenant(self.db,2,as_of=self.instant),WND_POLICY)
        recorded=self.pc4.resolve(tenant_id=2,key=SELECTOR_KEY,as_of=self.instant)
        self.assertEqual(recorded.value,"wnd.logpom")
        self.assertEqual(recorded.scope_id,2)

    def test_05_profile_without_pack_fails_closed(self):
        self.set_profile(6,"wnd.logpom")
        with self.assertRaisesRegex(OperationalPolicyBindingError,"PACK_INACTIVE"):
            self.resolve(6)

    def test_06_unknown_profile_with_pack_fails_closed(self):
        self.activate(5)
        self.set_profile(5,"unknown.profile")
        with self.assertRaisesRegex(OperationalPolicyBindingError,"PROFILE_UNKNOWN"):
            self.resolve(5)

    def test_07_independent_restaurant_active_no_profile_stays_neutral(self):
        self.activate(4)
        self.assertIs(self.resolve(4),NEUTRAL_POLICY)

    def test_08_past_effectivity_absent_profile_is_neutral(self):
        # Explicit future effective value is not applied earlier.
        self.assertIs(resolve_operational_policy(
            tenant_id=2,as_of=datetime(2026,10,8,tzinfo=timezone.utc),
            pack_authority=self.pk,operating_context=self.pc4,
        ),NEUTRAL_POLICY)

    def test_09_unmocked_r6_order_and_inventory_against_live_pc4_pk(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace as O
        from unittest.mock import patch
        from restaurant.r6.wnd_api_compat.orders_controller import OrdersController
        from restaurant.r6.wnd_api_compat.inventory_service import InventoryService
        from core.domain.inventory import taxonomy_profile as taxonomy
        fixture=json.loads((Path(__file__).parent/"vn0_n2_r1_preextraction_goldens.json").read_text())
        order=fixture["order_cases"][0]
        class Controller(OrdersController):
            def _taxonomy_path_for_atomic_unit(self,*args,**kwargs):
                return {"names":order["names"],"category":order["category"],
                        "subcategory":order["subcategory"]}
        result=Controller()._fulfillment_payload_for_item(
            self.db,tenant_id=2,atomic_unit_id=1,stored_status=order["status"])
        self.assertEqual(result,order["expected"])
        case=fixture["inventory_cases"][0]
        def node(id,name,level,parent=None):
            return O(id=id,name=name,semantic_level=level,parent_id=parent,sort_order=id)
        nodes={1:node(1,"Inventory","domain"),2:node(2,"Food","category",1),
               3:node(3,"Drinks","category",1),5:node(5,"Main Dish","subcategory",2),
               6:node(6,"Wine","subcategory",3)}
        unit=O(id=1,name=case["name"],meta=case["meta"])
        with patch.object(taxonomy,"_load_atomic_unit",return_value=unit),\
             patch.object(taxonomy,"_load_commerce_nodes",return_value=nodes),\
             patch.object(taxonomy,"_load_unit_commerce_mapping_nodes",
                          return_value=[nodes[i] for i in case["mappings"]]):
            output=InventoryService.get_inventory_profile(
                self.db,tenant_id=2,atomic_unit_id=1)
        self.assertEqual(output,case["expected"])

    def test_10_no_profile_active_restaurant_does_not_acquire_wnd_runtime(self):
        from restaurant.operational_policy_binding import resolve_for_tenant
        chosen=resolve_for_tenant(self.db,4,as_of=self.instant)
        self.assertIs(chosen,NEUTRAL_POLICY)
        self.assertIsNone(chosen.name_family("towel"))
        self.assertFalse(chosen.negative_stock("kitchen"))
        self.assertFalse(chosen.fulfillment({"MAIN DISH"},"MAIN DISH","", "waiting")["requires_preparation"])

    def test_11_disabled_pack_revokes_wnd_operational_policy(self):
        from pack_platform.contracts import DisablePack
        state=self.pk.state(2,"industry.restaurant")
        self.assertEqual(state.status.value,"active")
        self.pk.disable(DisablePack(
            "n2-r1-disable-2",2,"industry.restaurant",state.row_version,
            "disposable revocation proof",
        ))
        with self.assertRaisesRegex(OperationalPolicyBindingError,"PACK_INACTIVE"):
            self.resolve(2)

if __name__=="__main__":
    unittest.main()
