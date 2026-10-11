"""PC0 VN2 C2 A1-R1 exact future admission, R5 seal and pre-activation tests.

Governance-only: no HTTP route, database, pack or template side effects.
"""
from __future__ import annotations
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.platform.architecture_contract import (
    PC0ArchitectureError,
    _VN2_A1_AUTHORITY,
    _VN2_A1_EDGES,
    _VN2_A1_FUTURE,
    _VN2_A1_PREDECESSORS,
    _validate_vn2_a1_admission,
    _validate_vn2_a1_implementation_seal,
    _validate_vn2_a1_r5_validator_seal,
    _source_sha256,
    validate_pc0,
)

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/platform/v1"
PARENT="45f2313dbb57fc3f6b50638b279c2bf581234e5e"


def contract(name: str) -> dict:
    return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))


class VN2C2A1R1ContractTests(unittest.TestCase):
    def setUp(self):
        self.admission=contract("pc0_vn2_c2_discovery_admission.json")
        self.r5=contract("pc0_validator_successor_seal_r5.json")

    def reject_admission(self, mutate):
        candidate=copy.deepcopy(self.admission)
        mutate(candidate)
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-ADMISSION-DRIFT"):
            _validate_vn2_a1_admission(ROOT,candidate)

    def test_exact_authority_parent_and_route(self):
        self.assertEqual(_validate_vn2_a1_admission(ROOT),self.admission)
        self.assertEqual(self.admission["authority"],_VN2_A1_AUTHORITY)
        self.assertEqual(self.admission["parent_head"],PARENT)
        self.assertEqual(self.admission["contract_name"],"xbos.platform.pack-template-discovery.v1")
        self.assertEqual(self.admission["route"]["method"],"GET")
        self.assertEqual(self.admission["route"]["public_path"],"/api/kernel/platform/v1/pack-template-discovery")

    def test_exact_two_future_edge_admissions_without_general_policy(self):
        self.assertEqual(len(_VN2_A1_EDGES),2)
        self.assertEqual(_VN2_A1_EDGES,{
            ("core/auth/pack_template_discovery_router.py","database","identity","application"),
            ("core/auth/pack_template_discovery_router.py","pack_platform.discovery_read_model","identity","packs"),
        })
        p=contract("pc0_dependency_policy.json")
        self.assertNotIn("packs",p["allowed_directions"]["composition"])
        self.assertNotIn("application",p["allowed_directions"]["identity"])
        self.assertNotIn("packs",p["allowed_directions"]["identity"])
        self.assertEqual(p["allowed_directions"]["packs"],[])

    def test_third_edge_rejected(self):
        def mutation(c): c["exact_dependency_edges"].append({"source_path":"core/auth/other.py","import_name":"database","source_module":"identity","target_module":"application"})
        self.reject_admission(mutation)

    def test_wildcard_rejected(self):
        self.reject_admission(lambda c:c["exact_dependency_edges"][0].update({"source_path":"core/auth/*"}))

    def test_wrong_owner_rejected(self):
        self.reject_admission(lambda c:c["future_source_paths"][0].update({"owner":"PK"}))

    def test_wrong_module_rejected(self):
        self.reject_admission(lambda c:c["future_source_paths"][1].update({"module":"identity"}))

    def test_route_change_rejected(self):
        self.reject_admission(lambda c:c["route"].update({"public_path":"/api/kernel/other"}))

    def test_tenant_override_rejected(self):
        self.reject_admission(lambda c:c["security_invariants"].update({"header_tenant_authority":True}))

    def test_legacy_authority_rejected(self):
        self.reject_admission(lambda c:c["security_invariants"].update({"legacy_access_token_authority":True}))

    def test_entitlement_inference_rejected(self):
        self.reject_admission(lambda c:c["security_invariants"].update({"entitlement_field":True}))

    def test_general_policy_allow_rejected(self):
        self.reject_admission(lambda c:c["security_invariants"].update({"general_policy_allowance":True}))

    def test_write_authority_rejected(self):
        self.reject_admission(lambda c:c["read_only_invariants"].update({"no_data_writes":False}))

    def test_read_only_transaction_required(self):
        self.assertEqual(self.admission["read_only_invariants"]["db_transaction"],"READ ONLY")
        self.reject_admission(lambda c:c["read_only_invariants"].update({"db_transaction":"READ WRITE"}))

    def test_public_overlay_is_only_named_pk_read_model(self):
        overlay=self.admission["public_interface_overlay"]
        self.assertEqual(overlay["module"],"packs")
        self.assertEqual(overlay["owner"],"PK")
        self.assertEqual(overlay["add_public"],["pack_platform.discovery_read_model"])
        self.assertFalse(overlay["historical_interface_baseline_mutation"])
        self.assertEqual(len(overlay["private_repositories_preserved"]),2)
        self.reject_admission(lambda c:c["public_interface_overlay"]["add_public"].append("pack_platform.sql_repository"))

    def test_corrected_predecessors_match_c1_files(self):
        expected={
            "core/api/kernel_router.py":"243a6f77c8804eaff82cb131f8edc5d6dcd24e47ecafd6fa7f8ae660f2d97b00",
            "core/middleware/auth_middleware.py":"e03e258e5ebb574445b3a29e4db950f6ef80dde7b8fc344b45d7f781dc64b8d4",
            "core/platform/architecture_contract.py":"28515d9fda2ee909497cf0bb30fd3e4cfb04ecefcc99ec7e1eda60074078c888",
            "tests/contracts/test_pc0_kernel_boundaries.py":"1fc07557db90914d48a5a8cce23e485a71849649fb25f3e955580f249717d565",
        }
        self.assertEqual(_VN2_A1_PREDECESSORS,expected)
        for path in ("core/api/kernel_router.py","core/middleware/auth_middleware.py","tests/contracts/test_pc0_kernel_boundaries.py"):
            self.assertEqual(_source_sha256(ROOT/path),expected[path])
        self.assertNotEqual(_source_sha256(ROOT/"core/platform/architecture_contract.py"),expected["core/platform/architecture_contract.py"])

    def test_activation_absence_enforced_at_a1(self):
        self.assertFalse((CONTRACTS/"pc0_vn2_c2_discovery_implementation_seal.json").exists())
        for path in _VN2_A1_FUTURE:
            self.assertFalse((ROOT/path).exists())
        self.assertIsNone(_validate_vn2_a1_implementation_seal(ROOT))

    def test_unsealed_router_appearance_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ("contracts/platform/v1/pc0_vn2_c2_discovery_admission.json",
                         "core/api/kernel_router.py","core/middleware/auth_middleware.py"):
                dest=root/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,dest)
            self.assertIsNone(_validate_vn2_a1_implementation_seal(root))
            unexpected=root/_VN2_A1_FUTURE[0]
            unexpected.parent.mkdir(parents=True,exist_ok=True)
            unexpected.write_text("from database import get_db\n",encoding="utf-8")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-PREACTIVATION-SOURCE"):
                _validate_vn2_a1_implementation_seal(root)

    def test_unsealed_read_model_appearance_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ("contracts/platform/v1/pc0_vn2_c2_discovery_admission.json",
                         "core/api/kernel_router.py","core/middleware/auth_middleware.py"):
                dest=root/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,dest)
            unexpected=root/_VN2_A1_FUTURE[1]
            unexpected.parent.mkdir(parents=True,exist_ok=True)
            unexpected.write_text("SELECT = True\n",encoding="utf-8")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-PREACTIVATION-SOURCE"):
                _validate_vn2_a1_implementation_seal(root)

    def test_changed_kernel_without_implementation_seal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ("contracts/platform/v1/pc0_vn2_c2_discovery_admission.json",
                         "core/api/kernel_router.py","core/middleware/auth_middleware.py"):
                dest=root/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,dest)
            kernel=root/"core/api/kernel_router.py"
            kernel.write_bytes(kernel.read_bytes()+b"\n# unauthorized change\n")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-PREACTIVATION-SOURCE"):
                _validate_vn2_a1_implementation_seal(root)

    def test_changed_auth_without_implementation_seal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ("contracts/platform/v1/pc0_vn2_c2_discovery_admission.json",
                         "core/api/kernel_router.py","core/middleware/auth_middleware.py"):
                dest=root/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,dest)
            auth=root/"core/middleware/auth_middleware.py"
            auth.write_bytes(auth.read_bytes()+b"\n# unauthorized change\n")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-PREACTIVATION-SOURCE"):
                _validate_vn2_a1_implementation_seal(root)

    def test_future_implementation_seal_cannot_self_admit_fifth_edge(self):
        bogus={
            "schema":"xbos.platform.pc0-vn2-c2-discovery-implementation-seal.v1",
            "authority":"XBOS-NEUTRAL-VN2-R1-C2",
            "admission_parent_head":PARENT,
            "files":[],
            "exact_dependency_edges":self.admission["exact_dependency_edges"]+[{"source_path":"x","import_name":"settings","source_module":"packs","target_module":"application"}],
            "required_route_markers":{},
            "read_only_markers":{},
        }
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-C2-IMPLEMENTATION-AUTHORITY"):
            _validate_vn2_a1_implementation_seal(ROOT,bogus)

    def test_r5_seals_only_current_validator_and_matches_successor(self):
        self.assertEqual(self.r5["accepted_predecessor_commit"],PARENT)
        self.assertEqual(self.r5["authority"],_VN2_A1_AUTHORITY)
        self.assertEqual(len(self.r5["files"]),1)
        self.assertEqual(self.r5["files"][0]["path"],"core/platform/architecture_contract.py")
        self.assertEqual(self.r5["files"][0]["predecessor_sha256"],_VN2_A1_PREDECESSORS["core/platform/architecture_contract.py"])
        self.assertEqual(_validate_vn2_a1_r5_validator_seal(ROOT),_source_sha256(ROOT/"core/platform/architecture_contract.py"))

    def test_r5_extra_path_rejected(self):
        wrong=copy.deepcopy(self.r5)
        wrong["files"].append(copy.deepcopy(wrong["files"][0]))
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-R5-BOUNDS"):
            _validate_vn2_a1_r5_validator_seal(ROOT,wrong)

    def test_r5_wrong_predecessor_rejected(self):
        wrong=copy.deepcopy(self.r5)
        wrong["files"][0]["predecessor_sha256"]="0"*64
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-R5-BOUNDS"):
            _validate_vn2_a1_r5_validator_seal(ROOT,wrong)

    def test_r5_wrong_authority_rejected(self):
        wrong=copy.deepcopy(self.r5)
        wrong["authority"]="unauthorized"
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-R5-AUTHORITY"):
            _validate_vn2_a1_r5_validator_seal(ROOT,wrong)

    def test_r5_wrong_source_hash_rejected(self):
        wrong=copy.deepcopy(self.r5)
        wrong["files"][0]["successor_sha256"]="0"*64
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-VN2-A1-R5-SOURCE-CHANGED"):
            _validate_vn2_a1_r5_validator_seal(ROOT,wrong)

    def test_r5_previous_seals_remain_read_only_and_immutable(self):
        self.assertEqual(_validate_vn2_a1_r5_validator_seal(ROOT),self.r5["files"][0]["successor_sha256"])
        r3=contract("pc0_validator_successor_seal.json")
        r4=contract("pc0_validator_successor_seal_r4.json")
        self.assertEqual(r3["files"][0]["successor_sha256"],r4["files"][0]["predecessor_sha256"])
        self.assertEqual(r4["files"][0]["successor_sha256"],self.r5["files"][0]["predecessor_sha256"])
        self.assertEqual(r4["files"][1]["successor_sha256"],_source_sha256(ROOT/"tests/contracts/test_pc0_kernel_boundaries.py"))

    def test_release_integrity_real_repo(self):
        result=validate_pc0(ROOT)
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["successor_dependency_edge_count"],10)
        self.assertEqual(result["release_artifact_count"],22)


if __name__=="__main__":
    unittest.main()
