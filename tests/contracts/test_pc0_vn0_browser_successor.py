"""PC0 additive VN0-C2 kernel successor: strict historical and marker checks."""
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
    _VN0_C2_KERNEL_SHA256,
    _validate_vn0_browser_successor,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = "contracts/platform/v1/pc0_vn0_browser_session_successor.json"
KERNEL_PATH = "core/api/kernel_router.py"


class PC0VN0BrowserSuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))

    def test_valid_accepted_c2_registration(self):
        self.assertEqual(self.contract, _validate_vn0_browser_successor(ROOT))

    def _reject(self, contract, error):
        with self.assertRaisesRegex(PC0ArchitectureError, error):
            _validate_vn0_browser_successor(ROOT, contract)

    def test_incorrect_accepted_commit_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["accepted_commit"] = "0" * 40
        self._reject(bad, "PC0-VN0-C2-SUCCESSOR-IDENTITY")

    def test_incorrect_successor_hash_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["successor_sha256"] = "0" * 64
        self._reject(bad, "PC0-VN0-C2-SUCCESSOR-IDENTITY")

    def test_historical_nce_hash_rewrite_fails(self):
        bad = deepcopy(self.contract)
        bad["historical_nce"]["kernel_sha256"] = "0" * 64
        self._reject(bad, "PC0-VN0-NCE-HISTORY-CHANGED")

    def test_removed_required_browser_import_marker_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["required_markers"].pop(0)
        self._reject(bad, "PC0-VN0-C2-BROWSER-MARKERS")

    def test_removed_browser_router_composition_marker_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["required_markers"].pop(1)
        self._reject(bad, "PC0-VN0-C2-BROWSER-MARKERS")

    def test_removed_nce_import_marker_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["preserved_nce_markers"].pop(0)
        self._reject(bad, "PC0-VN0-C2-NCE-MARKERS")

    def test_removed_nce_prefix_marker_fails(self):
        bad = deepcopy(self.contract)
        bad["vn0_c2"]["preserved_nce_markers"].pop(1)
        self._reject(bad, "PC0-VN0-C2-NCE-MARKERS")

    def test_mutated_kernel_without_successor_fails(self):
        with tempfile.TemporaryDirectory(prefix="pc0-vn0-successor-") as directory:
            candidate = Path(directory)
            dest = candidate / KERNEL_PATH
            dest.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / KERNEL_PATH, dest)
            (candidate / CONTRACT_PATH).parent.mkdir(parents=True)
            (candidate / CONTRACT_PATH).write_text(json.dumps(self.contract), encoding="utf-8")
            dest.write_text(dest.read_text(encoding="utf-8") + "\n# unauthorized edit\n", encoding="utf-8")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-VN0-C2-KERNEL-CHANGED"):
                _validate_vn0_browser_successor(candidate)

    def test_missing_registration_is_not_accepted(self):
        with tempfile.TemporaryDirectory(prefix="pc0-vn0-missing-") as directory:
            candidate = Path(directory)
            dest = candidate / KERNEL_PATH
            dest.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / KERNEL_PATH, dest)
            self.assertIsNone(_validate_vn0_browser_successor(candidate))

    def test_exact_markers_are_checked_after_hash_guard(self):
        # The content digest normally catches mutations first. Mock only
        # that digest for this unit case to exercise each marker guard.
        for marker_type, error in (
            ("browser_import", "PC0-VN0-C2-BROWSER-MARKER-MISSING"),
            ("browser_include", "PC0-VN0-C2-BROWSER-MARKER-MISSING"),
            ("nce_import", "PC0-VN0-C2-NCE-MARKER-MISSING"),
            ("nce_prefix", "PC0-VN0-C2-NCE-MARKER-MISSING"),
        ):
            with self.subTest(marker=marker_type), tempfile.TemporaryDirectory(prefix="pc0-marker-") as directory:
                candidate = Path(directory)
                dest = candidate / KERNEL_PATH
                dest.parent.mkdir(parents=True)
                src = (ROOT / KERNEL_PATH).read_text(encoding="utf-8")
                marker = {
                    "browser_import": self.contract["vn0_c2"]["required_markers"][0],
                    "browser_include": self.contract["vn0_c2"]["required_markers"][1],
                    "nce_import": self.contract["vn0_c2"]["preserved_nce_markers"][0],
                    "nce_prefix": self.contract["vn0_c2"]["preserved_nce_markers"][1],
                }[marker_type]
                self.assertIn(marker, src)
                dest.write_text(src.replace(marker, "removed_authority_marker"), encoding="utf-8")
                with patch("core.platform.architecture_contract._source_sha256",
                           return_value=_VN0_C2_KERNEL_SHA256):
                    with self.assertRaisesRegex(PC0ArchitectureError, error):
                        _validate_vn0_browser_successor(candidate, self.contract)


if __name__ == "__main__":
    unittest.main()
