"""PC0-R3 exact non-finance migration/module/dependency/seal contract proofs.

No database access, migrations, runtime mutations or hosted effects.
All injected source modifications live under temporary directories.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from core.platform.architecture_contract import (
    PC0ArchitectureError,
    _PC0_R3_MIGRATIONS,
    _PC0_R3_N2_MODULE,
    _PC0_R3_N2_EDGES,
    _PC0_R3_R2_PREDECESSOR_SHA256,
    _pc0_r3_sealed_successor,
    _source_sha256,
    _tree_fingerprint,
    _validate_pc0_r3_migration_extensions,
    _validate_pc0_r3_policy_module,
    _validate_pc0_r3_policy_edges,
    _validate_pc0_r3_validator_seal,
    validate_pc0,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = "contracts/platform/v1"


def contract(name: str) -> dict:
    return json.loads((ROOT / CONTRACTS / name).read_text(encoding="utf-8"))


class PC0R3DescendantSuccessorTests(unittest.TestCase):
    def test_migration_ten_exact_accepted_artifacts(self):
        approved = _validate_pc0_r3_migration_extensions(ROOT)
        self.assertEqual(10, len(approved))
        self.assertEqual(set(approved), set(_PC0_R3_MIGRATIONS))

    def test_wrong_migration_commit_rejected(self):
        data = contract("pc0_non_finance_migration_successors.json")
        data["extensions"][0]["accepted_commit"] = "0" * 40
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-MIGRATION-PROVENANCE"):
            _validate_pc0_r3_migration_extensions(ROOT, data)

    def test_migration_hash_or_owner_rejected(self):
        for field, value in (("sha256", "0"*64), ("owner", "Finance")):
            with self.subTest(field=field):
                data = contract("pc0_non_finance_migration_successors.json")
                data["extensions"][1][field] = value
                with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-MIGRATION-PROVENANCE"):
                    _validate_pc0_r3_migration_extensions(ROOT, data)

    def test_wildcard_and_unregistered_migration_rejected(self):
        for name in ("versions/*.py", "versions/unregistered_052.py"):
            with self.subTest(path=name):
                data = contract("pc0_non_finance_migration_successors.json")
                data["extensions"][2]["path"] = name
                with self.assertRaises(PC0ArchitectureError):
                    _validate_pc0_r3_migration_extensions(ROOT, data)

    def test_missing_accepted_migration_rejected(self):
        data = contract("pc0_non_finance_migration_successors.json")
        data["extensions"].pop()
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-MIGRATION-COUNT"):
            _validate_pc0_r3_migration_extensions(ROOT, data)

    def test_accepted_migration_source_mutation_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r3-migration-") as directory:
            fake_root = Path(directory)
            for item in contract("pc0_non_finance_migration_successors.json")["extensions"]:
                target = fake_root / "alembic_neutral" / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "alembic_neutral" / item["path"], target)
            self.assertEqual(10, len(_validate_pc0_r3_migration_extensions(
                fake_root, contract("pc0_non_finance_migration_successors.json"))))
            target = fake_root / "alembic_neutral" / "versions/browser_session_v1_051.py"
            target.write_bytes(target.read_bytes() + b"\n# unauthorized\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-MIGRATION-SOURCE-CHANGED"):
                _validate_pc0_r3_migration_extensions(
                    fake_root, contract("pc0_non_finance_migration_successors.json"))

    def test_unregistered_052_file_cannot_extend_inventory(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r3-new-migration-") as directory:
            root = Path(directory)
            target = root / "alembic_neutral" / "versions/unregistered_052.py"
            target.parent.mkdir(parents=True)
            target.write_text('revision = "unregistered_052"\n', encoding="utf-8")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-FROZEN-FINANCE-INVENTORY"):
                _tree_fingerprint(root, "alembic_neutral", [], {})

    def test_module_is_exact_neutral_n2_source(self):
        module = _validate_pc0_r3_policy_module(ROOT)
        self.assertEqual(module["code"], "operational_policy")
        self.assertEqual(module["source_roots"], ["core/domain/operational_policy.py"])
        self.assertEqual(module["kind"], "shared_policy_contract")

    def test_restaurant_module_ownership_rejected(self):
        data = contract("pc0_n2_operational_policy_successor.json")
        data["module"]["owner"] = "Restaurant Pack"
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-N2-MODULE-CONTRACT"):
            _validate_pc0_r3_policy_module(ROOT, data)

    def test_module_root_wildcard_rejected(self):
        data = contract("pc0_n2_operational_policy_successor.json")
        data["module"]["source_roots"] = ["core/domain/*"]
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-N2-MODULE-CONTRACT"):
            _validate_pc0_r3_policy_module(ROOT, data)

    def test_unmapped_neutral_module_without_successor_fails(self):
        data = contract("pc0_n2_operational_policy_successor.json")
        data["module"]["source_roots"] = []
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-N2-MODULE-CONTRACT"):
            _validate_pc0_r3_policy_module(ROOT, data)

    def test_only_four_exact_accepted_n2_dependency_edges(self):
        edges = _validate_pc0_r3_policy_edges(ROOT)
        self.assertEqual(4, len(edges))
        self.assertEqual(4, len(_PC0_R3_N2_EDGES))

    def test_unauthorized_import_edge_rejected(self):
        data = contract("pc0_n2_operational_policy_edges.json")
        data["edges"].append({
            "source_path":"core/auth/browser_session_router.py",
            "import_name":"database",
            "source_module":"identity",
            "target_module":"application",
            "accepted_commit":"51057262faf7288e0ba4a8d488c8f2ff94e5cbe0",
            "accepted_authority":"XBOS-NEUTRAL-F-R1-B1-C2",
        })
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-N2-DEPENDENCY-CONTRACT"):
            _validate_pc0_r3_policy_edges(ROOT, data)

    def test_wrong_n2_import_commit_rejected(self):
        data = contract("pc0_n2_operational_policy_edges.json")
        data["edges"][0]["accepted_commit"] = "0"*40
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-N2-DEPENDENCY-CONTRACT"):
            _validate_pc0_r3_policy_edges(ROOT, data)

    def test_validator_seal_positive_exact_source(self):
        result = _validate_pc0_r3_validator_seal(ROOT)
        self.assertEqual(
            {"core/platform/architecture_contract.py": _source_sha256(
                ROOT / "core/platform/architecture_contract.py")}, result)
        previous = "5345e6655603ae89416568a4548dc798289f2b1702fe066cf51c29e90df64d7b"
        self.assertEqual(result["core/platform/architecture_contract.py"],
                         _pc0_r3_sealed_successor(ROOT,"core/platform/architecture_contract.py",previous))

    def test_validator_seal_wrong_predecessor(self):
        data = contract("pc0_validator_successor_seal.json")
        data["accepted_predecessor_commit"] = "0"*40
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-AUTHORITY"):
            _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_wrong_authority(self):
        data = contract("pc0_validator_successor_seal.json")
        data["authority"] = "UNAUTHORIZED"
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-AUTHORITY"):
            _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_wrong_predecessor_hash(self):
        data = contract("pc0_validator_successor_seal.json")
        data["files"][0]["predecessor_sha256"] = "0"*64
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-PREDECESSOR"):
            _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_wrong_successor_hash(self):
        data = contract("pc0_validator_successor_seal.json")
        data["files"][0]["successor_sha256"] = "0"*64
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-SOURCE-CHANGED"):
            _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_extra_business_or_kernel_path(self):
        for malicious in ("core/api/kernel_router.py","core/domain/inventory/service.py","*"):
            with self.subTest(path=malicious):
                data = contract("pc0_validator_successor_seal.json")
                data["files"].append({"path":malicious,"predecessor_sha256":"0"*64,
                                     "successor_sha256":"0"*64})
                with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-FILE-COUNT"):
                    _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_replaces_only_exact_validator_path(self):
        data = contract("pc0_validator_successor_seal.json")
        data["files"][0]["path"] = "core/api/kernel_router.py"
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-UNAUTHORIZED-PATH"):
            _validate_pc0_r3_validator_seal(ROOT, data)

    def test_validator_seal_absence_rejected(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r3-seal-absent-") as dirname:
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-CONTRACT-READ"):
                _validate_pc0_r3_validator_seal(Path(dirname))

    def test_validator_seal_post_attestation_source_mutation_fails(self):
        with tempfile.TemporaryDirectory(prefix="pc0-r3-seal-mutation-") as dirname:
            root = Path(dirname)
            validator = root / "core/platform/architecture_contract.py"
            validator.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "core/platform/architecture_contract.py", validator)
            self.assertEqual(_validate_pc0_r3_validator_seal(
                root, contract("pc0_validator_successor_seal.json")
            )["core/platform/architecture_contract.py"], _source_sha256(validator))
            validator.write_bytes(validator.read_bytes()+b"\n# post-seal edit\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R3-SEAL-SOURCE-CHANGED"):
                _validate_pc0_r3_validator_seal(
                    root, contract("pc0_validator_successor_seal.json"))

    def test_no_source_commit_self_reference(self):
        self.assertEqual(
            contract("pc0_validator_successor_seal.json")["accepted_predecessor_commit"],
            "6d3c8940d99bcda77f6522200999ef0e79859792")
        self.assertEqual(_PC0_R3_R2_PREDECESSOR_SHA256,
            "2a0bccd2cc0301fca71badf6e5cc004e287a9f687d4cdf123f74ddf8f5a05689")
        self.assertEqual(
            len(contract("pc0_validator_successor_seal.json")["files"]), 1)

    def test_full_pc0_fails_closed_on_c2_edges_not_authorized_by_r3(self):
        with self.assertRaisesRegex(PC0ArchitectureError, "PC0-DEPENDENCY-DENIED"):
            validate_pc0(ROOT)


if __name__ == "__main__":
    unittest.main()
