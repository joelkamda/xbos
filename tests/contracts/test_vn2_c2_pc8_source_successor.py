"""VN2 C2 PC8-R1 exact middleware descendant / validator R7 proof.

Tests operate only on temporary file copies; no database or production mutation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.platform.architecture_contract import (
    PC0ArchitectureError,
    _PC0_R7_C2_MIDDLEWARE_PREDECESSOR,
    _PC0_R7_C2_MIDDLEWARE_SHA,
    _PC0_R7_PREDECESSOR,
    _validate_pc0_r6_validator_seal,
    _validate_pc0_r7_validator_seal,
    _validate_pc0_r8_successor_seal,
    _validate_vn2_a1_implementation_seal,
    _source_sha256,
    validate_pc0,
)

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = (
    "contracts/platform/v1/pc0_validator_successor_seal.json",
    "contracts/platform/v1/pc0_validator_successor_seal_r4.json",
    "contracts/platform/v1/pc0_validator_successor_seal_r5.json",
    "contracts/platform/v1/pc0_validator_successor_seal_r6.json",
    "contracts/platform/v1/pc0_validator_successor_seal_r7.json",
    "contracts/platform/v1/pc0_validator_successor_seal_r8.json",
    "contracts/platform/v1/pc0_vn2_c2_discovery_admission.json",
    "contracts/platform/v1/vn2_pack_template_discovery_v1.json",
    "contracts/platform/v1/pc0_vn2_c2_discovery_implementation_seal.json",
    "contracts/platform/v1/pc8_release_manifest.json",
    "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json",
    "core/platform/architecture_contract.py",
    "tests/contracts/test_pc0_kernel_boundaries.py",
    "tests/contracts/test_vn2_c2_pc8_source_successor.py",
    "core/auth/pack_template_discovery_router.py",
    "pack_platform/discovery_read_model.py",
    "core/api/kernel_router.py",
    "core/middleware/auth_middleware.py",
)
R7 = "contracts/platform/v1/pc0_validator_successor_seal_r7.json"
C2 = "contracts/platform/v1/pc0_vn2_c2_discovery_implementation_seal.json"
MIDDLEWARE = "core/middleware/auth_middleware.py"
VALIDATOR = "core/platform/architecture_contract.py"


def sha_git(commit: str, path: str) -> str:
    source = subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"]
    )
    return hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()


class TemporaryGovernanceRoot:
    def __enter__(self) -> Path:
        self.context = tempfile.TemporaryDirectory(prefix="xbos_pc8_r1_")
        self.root = Path(self.context.__enter__())
        for relative in RELATIVE:
            dst = self.root / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dst)
        return self.root

    def __exit__(self, exc_type, exc, tb):
        return self.context.__exit__(exc_type, exc, tb)


def mutate_json(root: Path, relative: str, transform):
    path = root / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    transform(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class PC8ExactC2SuccessorTests(unittest.TestCase):
    def test_exact_seal_accepts_only_validator(self):
        historical_r7 = _validate_pc0_r7_validator_seal(ROOT, historical_only=True)
        self.assertEqual(
            historical_r7,
            "8bf6405ce9769edb791a7a9d002c345351701537bc0153212a41cc77f54445d8",
        )
        self.assertEqual(
            _validate_pc0_r8_successor_seal(ROOT)[VALIDATOR],
            _source_sha256(ROOT / VALIDATOR),
        )
        self.assertNotEqual(historical_r7, _source_sha256(ROOT / VALIDATOR))
        seal = json.loads((ROOT / R7).read_text(encoding="utf-8"))
        self.assertEqual(seal["schema"], "xbos.platform.pc0-validator-successor-seal-r7.v1")
        self.assertEqual(seal["authority"], "XBOS-NEUTRAL-VN2-R1-C2-PC8-R1")
        self.assertEqual(seal["accepted_predecessor_commit"], "ab8a43456c572785ec9b61190bfbc3baef20f098")
        self.assertEqual(len(seal["files"]), 1)
        self.assertEqual(seal["files"][0]["path"], VALIDATOR)
        self.assertEqual(seal["files"][0]["predecessor_sha256"], _PC0_R7_PREDECESSOR)
        self.assertNotEqual(seal["files"][0]["successor_sha256"], _PC0_R7_PREDECESSOR)

    def test_historical_r5_r6_blobs_and_immutable_seals(self):
        self.assertEqual(
            sha_git("c5e031b437561363dcb94b43ca9b52ac25ddadf8", VALIDATOR),
            "75c42332159c9673a3e081eb6fc682303bdec8174a9a4e34c1ca6d9689d4d02f"
        )
        self.assertEqual(
            sha_git("8ff02c869e17c1a4c5fd5b5c5485109f4e86c253", VALIDATOR),
            _PC0_R7_PREDECESSOR
        )
        self.assertEqual(
            sha_git("8ff02c869e17c1a4c5fd5b5c5485109f4e86c253",
                    "tests/contracts/test_pc0_kernel_boundaries.py"),
            "7022b90767677e0707be6be752907405f7edb291561a9a4f6fb05a3f5e4c07ac"
        )
        self.assertEqual(
            _validate_pc0_r6_validator_seal(ROOT, historical_only=True)[VALIDATOR],
            _PC0_R7_PREDECESSOR
        )
        for filename, digest in (
            ("pc0_validator_successor_seal_r5.json",
             "8d2846131f4c4c9ac06a109de82574ad5b20fbd7639dfc366f0b7d2e87d898cd"),
            ("pc0_validator_successor_seal_r6.json",
             "dee99ca8480dc057bb12a23be44c0665bddaaec00225f3c3df2079f07a29352f"),
            ("pc0_vn2_c2_discovery_admission.json",
             "5a9501d193abd96918d6af8681a1ff9feedf5f73e3853c7600228c3b95f5c3e3"),
        ):
            self.assertEqual(_source_sha256(ROOT / "contracts/platform/v1" / filename), digest)

    def test_exact_c2_middleware_and_two_edge_seal(self):
        implementation = _validate_vn2_a1_implementation_seal(ROOT)
        self.assertEqual(implementation[MIDDLEWARE], _PC0_R7_C2_MIDDLEWARE_SHA)
        self.assertEqual(_PC0_R7_C2_MIDDLEWARE_PREDECESSOR,
                         "e03e258e5ebb574445b3a29e4db950f6ef80dde7b8fc344b45d7f781dc64b8d4")
        self.assertEqual(_source_sha256(ROOT / MIDDLEWARE), _PC0_R7_C2_MIDDLEWARE_SHA)
        seal = json.loads((ROOT / C2).read_text(encoding="utf-8"))
        self.assertEqual(len(seal["files"]), 4)
        self.assertEqual(len(seal["exact_dependency_edges"]), 2)
        self.assertEqual(
            {(edge["source_path"], edge["import_name"]) for edge in seal["exact_dependency_edges"]},
            {("core/auth/pack_template_discovery_router.py", "database"),
             ("core/auth/pack_template_discovery_router.py", "pack_platform.discovery_read_model")}
        )

    def test_real_pc0_complete(self):
        self.assertEqual(validate_pc0(ROOT)["status"], "PASS")

    def test_missing_c2_seal_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            (root / C2).unlink()
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-A1-PREACTIVATION-SOURCE"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_c2_middleware_digest_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda data: data["files"][1].update(
                {"successor_sha256": "0" * 64}
            ))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-UNSEALED"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_c2_predecessor_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda data: data["files"][1].update(
                {"predecessor_sha256": "0" * 64}
            ))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-PREDECESSOR"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_c2_authority_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda data: data.update({"authority": "attacker"}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-AUTHORITY"):
                _validate_pc0_r7_validator_seal(root)

    def test_forged_fifth_c2_source_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda data: data["files"].append({
                "path": "database.py", "predecessor_sha256": None,
                "successor_sha256": "0" * 64,
            }))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-PATHS"):
                _validate_pc0_r7_validator_seal(root)

    def test_third_edge_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, C2, lambda data: data["exact_dependency_edges"].append({
                "source_path": "pack_platform/discovery_read_model.py",
                "import_name": "database", "source_module": "packs",
                "target_module": "application",
            }))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-AUTHORITY"):
                _validate_pc0_r7_validator_seal(root)

    def test_unrelated_auth_middleware_change_fails_closed(self):
        with TemporaryGovernanceRoot() as root:
            with (root / MIDDLEWARE).open("a", encoding="utf-8") as file:
                file.write("\n# unrelated unapproved auth change\n")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN2-C2-IMPLEMENTATION-UNSEALED"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_r7_predecessor_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R7, lambda data: data["files"][0].update(
                {"predecessor_sha256": "0" * 64}
            ))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-PREDECESSOR"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_r7_successor_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R7, lambda data: data["files"][0].update(
                {"successor_sha256": "0" * 64}
            ))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-SUCCESSOR-CHANGED"):
                _validate_pc0_r7_validator_seal(root)

    def test_wrong_r7_authority_rejected(self):
        with TemporaryGovernanceRoot() as root:
            mutate_json(root, R7, lambda data: data.update({"authority": "forged"}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-AUTHORITY"):
                _validate_pc0_r7_validator_seal(root)

    def test_r7_extra_source_and_wildcard_rejected(self):
        with TemporaryGovernanceRoot() as root:
            seal = json.loads((root / R7).read_text(encoding="utf-8"))
            extra = copy.deepcopy(seal)
            extra["files"].append({"path": "database.py", "predecessor_sha256": "0" * 64,
                                    "successor_sha256": "1" * 64})
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-SOURCE-BOUNDS"):
                _validate_pc0_r7_validator_seal(root, extra)
            wildcard = copy.deepcopy(seal)
            wildcard["files"][0]["path"] = "core/platform/*"
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-SOURCE-BOUNDS"):
                _validate_pc0_r7_validator_seal(root, wildcard)

    def test_r6_seal_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            r6 = "contracts/platform/v1/pc0_validator_successor_seal_r6.json"
            mutate_json(root, r6, lambda data: data["files"][0].update(
                {"successor_sha256": "0" * 64}
            ))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-R6-HISTORY-CHANGED"):
                _validate_pc0_r7_validator_seal(root)

    def test_pc8_historical_manifest_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            pc8 = "contracts/platform/v1/pc8_release_manifest.json"
            mutate_json(root, pc8, lambda data: data.update({"unapproved": True}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-PC8-HISTORY-CHANGED"):
                _validate_pc0_r7_validator_seal(root)

    def test_pc8_successor_history_mutation_rejected(self):
        with TemporaryGovernanceRoot() as root:
            pc8 = "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json"
            mutate_json(root, pc8, lambda data: data.update({"unapproved": True}))
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-R7-PC8-HISTORY-CHANGED"):
                _validate_pc0_r7_validator_seal(root)

    def test_c1_contract_and_identity_boundary_preserved(self):
        c1 = ROOT / "contracts/platform/v1/vn2_pack_template_discovery_v1.json"
        contract = json.loads(c1.read_text(encoding="utf-8"))
        self.assertEqual(contract["contract_name"], "xbos.platform.pack-template-discovery.v1")
        self.assertEqual(contract["authentication"]["session_profile"], "browser-session.v1")
        adapter = (ROOT / "core/auth/pack_template_discovery_router.py").read_text(encoding="utf-8")
        self.assertIn("validate_browser_access", adapter)
        self.assertIn("AuthService().me", adapter)
        self.assertNotIn("X-Tenant-Code", adapter)
        self.assertNotIn("X-Branch-Code", adapter)


if __name__ == "__main__":
    unittest.main()
