"""PCR VN2-C2 PC0-R8 exact three-file successor proof; isolated and fail-closed."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from core.platform.architecture_contract import (
    PC0ArchitectureError,
    _PC0_R8_PREDECESSORS,
    _validate_pc0_r6_validator_seal,
    _validate_pc0_r7_validator_seal,
    _validate_pc0_r8_successor_seal,
    _validate_vn2_a1_implementation_seal,
    _source_sha256,
    validate_pc0,
)
from tests.contracts.test_vn2_c2_pc8_source_successor import (
    TemporaryGovernanceRoot,
    mutate_json,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = "contracts/platform/v1/"
R8 = CONTRACTS + "pc0_validator_successor_seal_r8.json"
R7 = CONTRACTS + "pc0_validator_successor_seal_r7.json"
R6 = CONTRACTS + "pc0_validator_successor_seal_r6.json"
C2 = CONTRACTS + "pc0_vn2_c2_discovery_implementation_seal.json"
PC8 = CONTRACTS + "pc8_release_manifest.json"
VALIDATOR = "core/platform/architecture_contract.py"
PC0_TEST = "tests/contracts/test_pc0_kernel_boundaries.py"
PC8_TEST = "tests/contracts/test_vn2_c2_pc8_source_successor.py"
KERNEL = "core/api/kernel_router.py"
AUTH = "core/middleware/auth_middleware.py"


def read_seal(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ExactR8LineageTests(unittest.TestCase):
    def test_three_exact_path_successors_and_live_hashes(self):
        seal = read_seal(ROOT / R8)
        self.assertEqual(seal["schema"], "xbos.platform.pc0-validator-and-test-successor-seal-r8.v1")
        self.assertEqual(seal["authority"], "XBOS-NEUTRAL-VN2-R1-C2-PC0-R8-R1")
        self.assertEqual(seal["accepted_predecessor_commit"], "ab8a43456c572785ec9b61190bfbc3baef20f098")
        self.assertEqual(len(seal["files"]), 3)
        actual = _validate_pc0_r8_successor_seal(ROOT)
        self.assertEqual(set(actual), {VALIDATOR, PC0_TEST, PC8_TEST})
        for item in seal["files"]:
            path = item["path"]
            self.assertEqual(item["predecessor_sha256"], _PC0_R8_PREDECESSORS[path])
            self.assertNotEqual(item["successor_sha256"], item["predecessor_sha256"])
            self.assertEqual(item["successor_sha256"], actual[path])
            self.assertEqual(actual[path], _source_sha256(ROOT / path))

    def test_r6_r7_r8_chain_is_exact(self):
        r6 = _validate_pc0_r6_validator_seal(ROOT, historical_only=True)
        r7 = _validate_pc0_r7_validator_seal(ROOT, historical_only=True)
        r8 = _validate_pc0_r8_successor_seal(ROOT)
        self.assertEqual(r6[VALIDATOR], "8d319746041073680268fd20f123a06c0190368083cd0e37b8b1565cfd5ffc9d")
        self.assertEqual(r6[PC0_TEST], _PC0_R8_PREDECESSORS[PC0_TEST])
        self.assertEqual(r7, _PC0_R8_PREDECESSORS[VALIDATOR])
        self.assertNotEqual(r7, r8[VALIDATOR])
        self.assertEqual(_source_sha256(ROOT / R7), "fc9244d72f24d4de4a1e1c57b83ce05f16968ef3364892219065b14c9f7979bd")

    def test_c2_exact_four_source_seal_two_edges(self):
        c2 = _validate_vn2_a1_implementation_seal(ROOT)
        self.assertEqual(set(c2), {KERNEL, AUTH, "core/auth/pack_template_discovery_router.py",
                                   "pack_platform/discovery_read_model.py"})
        contract = read_seal(ROOT / C2)
        self.assertEqual(len(contract["exact_dependency_edges"]), 2)
        self.assertEqual(c2[AUTH], "66797bd319cfcce3fceb4b75af256e704736cd140be2d67158d4a5a66e0cbb55")

    def test_real_pc0_pass_and_twelve_exact_edges(self):
        report = validate_pc0(ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["successor_dependency_edge_count"], 12)

    def test_missing_r8_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            (root / R8).unlink()
            with self.assertRaises(PC0ArchitectureError):
                _validate_pc0_r7_validator_seal(root)
            with self.assertRaises(PC0ArchitectureError):
                _validate_pc0_r8_successor_seal(root)

    def test_wrong_r8_authority_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R8, lambda x: x.update({"authority": "forged"}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-AUTHORITY"):
                _validate_pc0_r8_successor_seal(root)

    def test_wrong_r8_base_commit_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R8, lambda x: x.update({"accepted_predecessor_commit": "0" * 40}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-AUTHORITY"):
                _validate_pc0_r8_successor_seal(root)

    def test_wrong_r8_predecessor_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R8, lambda x: x["files"][0].update({"predecessor_sha256": "0" * 64}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-PREDECESSOR"):
                _validate_pc0_r8_successor_seal(root)

    def test_wrong_r8_successor_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R8, lambda x: x["files"][1].update({"successor_sha256": "0" * 64}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SUCCESSOR-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_extra_path_and_wildcard_rejected(self):
        with TemporaryGovernanceRoot() as root:
            seal = read_seal(root / R8)
            extra = copy.deepcopy(seal)
            extra["files"].append({"path": KERNEL, "predecessor_sha256": "0" * 64,
                                   "successor_sha256": "1" * 64})
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SOURCE-COUNT"):
                _validate_pc0_r8_successor_seal(root, extra)
            wildcard = copy.deepcopy(seal)
            wildcard["files"][2]["path"] = "tests/contracts/*"
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SOURCE-PATH"):
                _validate_pc0_r8_successor_seal(root, wildcard)

    def test_unrelated_pc0_test_change_rejected(self):
        with TemporaryGovernanceRoot() as root:
            with (root / PC0_TEST).open("a", encoding="utf-8") as handle:
                handle.write("\n# unauthorized alteration\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SUCCESSOR-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_unrelated_validator_change_rejected(self):
        with TemporaryGovernanceRoot() as root:
            with (root / VALIDATOR).open("a", encoding="utf-8") as handle:
                handle.write("\n# unauthorized alteration\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SUCCESSOR-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_unrelated_r7_test_change_rejected(self):
        with TemporaryGovernanceRoot() as root:
            with (root / PC8_TEST).open("a", encoding="utf-8") as handle:
                handle.write("\n# unauthorized alteration\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-SUCCESSOR-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_r7_seal_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R7, lambda x: x["files"][0].update({"successor_sha256": "0" * 64}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R8-R7-HISTORY-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_r6_seal_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R6, lambda x: x["files"][0].update({"successor_sha256": "0" * 64}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-R6-HISTORY-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_pc8_historical_manifest_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, PC8, lambda x: x.update({"unapproved": True}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-PC8-HISTORY-CHANGED"):
                _validate_pc0_r8_successor_seal(root)

    def test_unapproved_third_dependency_edge_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda x: x["exact_dependency_edges"].append({
                "source_path": "pack_platform/discovery_read_model.py", "import_name": "database",
                "source_module": "packs", "target_module": "application",
            }))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-AUTHORITY"):
                _validate_pc0_r8_successor_seal(root)

    def test_unsealed_kernel_rejected(self):
        with TemporaryGovernanceRoot() as root:
            with (root / KERNEL).open("a", encoding="utf-8") as handle:
                handle.write("\n# unauthorized kernel mutation\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-UNSEALED"):
                _validate_pc0_r8_successor_seal(root)

    def test_unsealed_middleware_rejected(self):
        with TemporaryGovernanceRoot() as root:
            with (root / AUTH).open("a", encoding="utf-8") as handle:
                handle.write("\n# unauthorized auth mutation\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-UNSEALED"):
                _validate_pc0_r8_successor_seal(root)

    def test_database_mutation_original_negative_fixture_still_proves(self):
        from tests.contracts.test_pc0_kernel_boundaries import PC0KernelBoundaryTests
        fixture = PC0KernelBoundaryTests("test_real_composition_source_change_fails")
        fixture.test_real_composition_source_change_fails()


if __name__ == "__main__":
    unittest.main()
