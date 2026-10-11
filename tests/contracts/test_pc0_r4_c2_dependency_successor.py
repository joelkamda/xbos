"""PC0-R4 source-provenanced VN0-C2 dependency and two-path validator seal."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from core.platform.architecture_contract import (
    PC0ArchitectureError,
    _PC0_R4_PREDECESSORS,
    _git_canonical_blob_sha1,
    _validate_pc0_r4_c2_edges,
    _validate_pc0_r4_validator_seal,
    validate_pc0,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform/v1"
COMMIT = "51057262faf7288e0ba4a8d488c8f2ff94e5cbe0"


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


class PC0R4C2DependencyTests(unittest.TestCase):
    def setUp(self):
        self.registry=load("pc0_vn0_c2_dependency_edges.json")
        self.seal=load("pc0_validator_successor_seal_r4.json")

    def _reject_edge(self, field, value, code="PC0-R4-C2-EDGE-PROVENANCE"):
        wrong=deepcopy(self.registry)
        wrong["edges"][0][field]=value
        with self.assertRaisesRegex(PC0ArchitectureError, code):
            _validate_pc0_r4_c2_edges(ROOT,wrong)

    def test_exact_four_and_byte_identical_to_accepted_c2(self):
        self.assertEqual(len(_validate_pc0_r4_c2_edges(ROOT)),4)
        self.assertEqual(len(self.registry["edges"]),4)
        for edge in self.registry["edges"]:
            with self.subTest(path=edge["source_path"]):
                path=edge["source_path"]
                historical=subprocess.check_output(["git","-C",str(ROOT),"show",COMMIT+":"+path])
                current=(ROOT/path).read_bytes().replace(b"\r\n",b"\n")
                self.assertEqual(historical,current)
                self.assertEqual(edge["source_git_blob"],_git_canonical_blob_sha1(current))
                self.assertEqual(edge["accepted_commit"],COMMIT)

    def test_fifth_edge_rejected(self):
        wrong=deepcopy(self.registry)
        wrong["edges"].append(deepcopy(wrong["edges"][0]))
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-C2-EDGE-COUNT"):
            _validate_pc0_r4_c2_edges(ROOT,wrong)

    def test_wrong_path_rejected(self):
        self._reject_edge("source_path","core/domain/inventory/service.py")

    def test_wrong_import_rejected(self):
        self._reject_edge("import_name","settings")

    def test_wrong_source_module_rejected(self):
        self._reject_edge("source_module","application")

    def test_wrong_target_module_rejected(self):
        self._reject_edge("target_module","identity")

    def test_wrong_commit_rejected(self):
        self._reject_edge("accepted_commit","0"*40)

    def test_wrong_authority_rejected(self):
        self._reject_edge("accepted_authority","OTHER")

    def test_wrong_source_blob_rejected(self):
        self._reject_edge("source_git_blob","0"*40)

    def test_wildcard_edge_rejected(self):
        self._reject_edge("source_path","core/auth/*")

    def test_global_identity_to_application_rule_remains_denied(self):
        policy=load("pc0_dependency_policy.json")
        self.assertNotIn("application",policy["allowed_directions"]["identity"])

    def test_c2_contract_missing_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r4-c2-missing-") as name:
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-CONTRACT-READ"):
                _validate_pc0_r4_c2_edges(Path(name))

    def test_c2_post_acceptance_mutation_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r4-c2-change-") as name:
            root=Path(name)
            for entry in self.registry["edges"]:
                target=root/entry["source_path"]
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/entry["source_path"],target)
            self.assertEqual(len(_validate_pc0_r4_c2_edges(root,self.registry)),4)
            target=root/self.registry["edges"][0]["source_path"]
            target.write_bytes(target.read_bytes()+b"\n# post C2 mutation\n")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-C2-SOURCE-CHANGED"):
                _validate_pc0_r4_c2_edges(root,self.registry)

    def test_validator_r4_two_exact_paths(self):
        result=_validate_pc0_r4_validator_seal(ROOT)
        self.assertEqual(len(result),2)
        self.assertEqual(set(result),set(_PC0_R4_PREDECESSORS))

    def test_wrong_r4_predecessor_commit_rejected(self):
        wrong=deepcopy(self.seal)
        wrong["accepted_predecessor_commit"]="0"*40
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-AUTHORITY"):
            _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_wrong_r4_authority_rejected(self):
        wrong=deepcopy(self.seal)
        wrong["authority"]="OTHER"
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-AUTHORITY"):
            _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_wrong_r4_successor_hash_rejected(self):
        wrong=deepcopy(self.seal)
        wrong["files"][0]["successor_sha256"]="0"*64
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-SOURCE-CHANGED"):
            _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_wrong_r4_predecessor_hash_rejected(self):
        wrong=deepcopy(self.seal)
        wrong["files"][0]["predecessor_sha256"]="0"*64
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-PREDECESSOR"):
            _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_business_kernel_auth_wildcard_seal_paths_rejected(self):
        for path in ["core/api/kernel_router.py","core/auth/browser_session_router.py","core/domain/inventory/service.py","*"]:
            with self.subTest(path=path):
                wrong=deepcopy(self.seal)
                wrong["files"][0]["path"]=path
                with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-UNAUTHORIZED-PATH"):
                    _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_extra_sealed_path_rejected(self):
        wrong=deepcopy(self.seal)
        wrong["files"].append(deepcopy(wrong["files"][0]))
        with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-COUNT"):
            _validate_pc0_r4_validator_seal(ROOT,wrong)

    def test_missing_r4_seal_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r4-seal-missing-") as name:
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-CONTRACT-READ"):
                _validate_pc0_r4_validator_seal(Path(name))

    def test_post_seal_file_mutation_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r4-seal-change-") as name:
            root=Path(name)
            for entry in self.seal["files"]:
                target=root/entry["path"]
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/entry["path"],target)
            r3=root/"contracts/platform/v1/pc0_validator_successor_seal.json"
            r3.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(CONTRACTS/"pc0_validator_successor_seal.json",r3)
            self.assertEqual(len(_validate_pc0_r4_validator_seal(root,self.seal)),2)
            victim=root/self.seal["files"][0]["path"]
            victim.write_bytes(victim.read_bytes()+b"\n# unauthorized post seal\n")
            with self.assertRaisesRegex(PC0ArchitectureError,"PC0-R4-SEAL-SOURCE-CHANGED"):
                _validate_pc0_r4_validator_seal(root,self.seal)

    def test_pc0_full_release_integrity_and_exact_admitted_edges(self):
        result=validate_pc0(ROOT)
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["successor_dependency_edge_count"],10)
        self.assertEqual(result["release_artifact_count"],22)


if __name__=="__main__":
    unittest.main()
