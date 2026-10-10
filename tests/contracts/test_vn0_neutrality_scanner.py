"""VN0 semantic scanner conformance, negative injections and allowed zones.

No application files are modified during injection; all synthetic source is
created under OS-managed temporary directories.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import subprocess
import sys
import json

from scripts.verify_vn0_neutrality import ROOT, scan, _scan_python


class VN0SharedRuntimeScannerTests(unittest.TestCase):
    def test_positive_real_accepted_source(self):
        self.assertEqual(scan(ROOT), [])

    def test_accepted_n2_r1_head_scans_without_semantic_findings(self):
        accepted = "93198dafff6f1e0809e6dba2b9e4352d8a6037a8"
        for relative in (
            "core/api/orders/orders_controller.py",
            "core/domain/inventory/taxonomy_profile.py",
            "core/domain/inventory/service.py",
            "core/integrations/xafpay_v2/contract.py",
        ):
            with self.subTest(relative=relative):
                original = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", accepted + ":" + relative],
                ).decode("utf-8-sig")
                self.assertEqual(_scan_python(original, relative), [])

    def _scan_injected(self, relative: str, source: str):
        with tempfile.TemporaryDirectory(prefix="xbos-vn0-neutral-") as temporary:
            root = Path(temporary)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            return scan(root)

    def test_detects_direct_wnd_policy_core_import(self):
        findings = self._scan_injected(
            "core/domain/inventory/unsafe.py",
            "from restaurant.wnd_operational_policy import WND_POLICY\n",
        )
        self.assertIn("DIRECT_WND_POLICY_IMPORT", {x.code for x in findings})

    def test_detects_hardcoded_tenant_id_policy(self):
        findings = self._scan_injected(
            "core/api/orders/unsafe.py",
            "def select(tenant_id):\n    if tenant_id == 2:\n        return 'special'\n",
        )
        self.assertIn("HARDCODED_TENANT_TWO_BRANCH", {x.code for x in findings})

    def test_detects_tenant_name_policy(self):
        findings = self._scan_injected(
            "core/api/orders/unsafe.py",
            'def select(tenant_name):\n    if tenant_name == "WND":\n        return "special"\n',
        )
        self.assertIn("WND_TENANT_IDENTITY_BRANCH", {x.code for x in findings})

    def test_detects_explicit_wnd_profile_in_shared_core(self):
        findings = self._scan_injected(
            "core/domain/inventory/unsafe.py",
            'def select(config):\n    if config == "wnd.logpom":\n        return "special"\n',
        )
        self.assertIn("WND_PROFILE_SELECTOR_IN_CORE", {x.code for x in findings})

    def test_detects_generic_restaurant_route_authority(self):
        findings = self._scan_injected(
            "core/api/orders/unsafe.py",
            'KITCHEN_ROUTE_NAMES = {"MAIN DISH", "BREAKFAST"}\n',
        )
        self.assertIn("RESTAURANT_ROUTE_CONSTANT_IN_CORE", {x.code for x in findings})

    def test_detects_restaurant_menu_alias_in_shared_inventory(self):
        findings = self._scan_injected(
            "core/domain/inventory/unsafe.py",
            'FOOD_KEYWORDS = {"towel", "ndole"}\n',
        )
        self.assertIn("RESTAURANT_KEYWORD_CONSTANT_IN_CORE", {x.code for x in findings})

    def test_detects_generic_kitchen_negative_stock(self):
        findings = self._scan_injected(
            "core/domain/inventory/unsafe.py",
            'def negative(family):\n    if family == "kitchen":\n        return True\n    return False\n',
        )
        self.assertIn("IMPLICIT_RESTAURANT_NEGATIVE_STOCK", {x.code for x in findings})

    def test_detects_indirect_negative_stock_assignment(self):
        findings = self._scan_injected(
            "core/domain/inventory/unsafe.py",
            'def negative(inventory_family):\n'
            '    allow_negative_stock = inventory_family == "kitchen"\n'
            '    return allow_negative_stock\n',
        )
        self.assertIn("IMPLICIT_RESTAURANT_NEGATIVE_STOCK", {x.code for x in findings})

    def test_negative_cli_fails_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory(prefix="xbos-vn0-cli-negative-") as temporary:
            root = Path(temporary)
            target = root / "core/domain/inventory/unsafe.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                'from restaurant.wnd_operational_policy import WND_POLICY\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/verify_vn0_neutrality.py"),
                 "--root", str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(report["blocking_count"], 1)

    def test_allowed_zones_do_not_fail_despite_explicit_wnd_source(self):
        with tempfile.TemporaryDirectory(prefix="xbos-vn0-allowed-") as temporary:
            root = Path(temporary)
            allowed = (
                "restaurant/wnd_operational_policy.py",
                "restaurant/r6/wnd_api_compat/orders_controller.py",
                "alembic_neutral/versions/legacy_wnd.py",
                "tests/contracts/test_wnd_golden.py",
                "docs/wnd_history.py",
                "core/platform/neutral_proof/service.py",
            )
            for relative in allowed:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    'from restaurant.wnd_operational_policy import WND_POLICY\n'
                    'def policy(tenant_id):\n'
                    '    if tenant_id == 2: return WND_POLICY\n',
                    encoding="utf-8",
                )
            self.assertEqual(scan(root), [])

    def test_generic_integration_diagnostic_text_is_not_authority(self):
        findings = self._scan_injected(
            "core/integrations/xafpay_v2/contract.py",
            'def validate(currency):\n'
            '    if currency != "XAF":\n'
            '        raise ValueError("WND checkout requires XAF")\n',
        )
        self.assertEqual(findings, [])

    def test_boot_composition_is_covered(self):
        findings = self._scan_injected(
            "startup.py",
            'from restaurant.wnd_operational_policy import WND_POLICY\n',
        )
        self.assertIn("DIRECT_WND_POLICY_IMPORT", {x.code for x in findings})


if __name__ == "__main__":
    unittest.main()
