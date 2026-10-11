"""PC0-R2: exact accepted historical source lineage, negative injections."""
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
    _POST_NCE_TRUSTED,
    _pc8_composition_replacements,
    _post_nce_resolved_hash,
    _source_sha256,
    _validate_post_nce_source_successors,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "contracts/platform/v1/pc0_post_nce_source_successors.json"


class PC0PostNCESuccessorTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def _reject(self, proposed, code):
        with self.assertRaisesRegex(PC0ArchitectureError, code):
            _validate_post_nce_source_successors(ROOT, proposed)

    def test_full_accepted_git_history_exact(self):
        result = _validate_post_nce_source_successors(ROOT)
        self.assertEqual(6, len(result))
        self.assertEqual(17, sum(len(item["successors"]) for item in self.contract["paths"]))
        for item in self.contract["paths"]:
            with self.subTest(path=item["path"]):
                path = item["path"]
                source = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show",
                     item["historical_anchor_commit"] + ":" + path]
                )
                def digest(blob):
                    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()
                self.assertEqual(item["historical_anchor_sha256"], digest(source))
                for entry in item["successors"]:
                    source = subprocess.check_output(
                        ["git", "-C", str(ROOT), "show",
                         entry["accepted_commit"] + ":" + path]
                    )
                    self.assertEqual(entry["successor_sha256"], digest(source))
                self.assertEqual(result[path], item["successors"][-1]["successor_sha256"])

    def test_wrong_predecessor_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][1]["successors"][-1]["predecessor_sha256"] = "0" * 64
        self._reject(c, "PC0-POST-NCE-BROKEN-CHAIN")

    def test_wrong_successor_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][1]["successors"][-1]["successor_sha256"] = "0" * 64
        self._reject(c, "PC0-POST-NCE-SOURCE-HASH")

    def test_wrong_accepted_commit_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][1]["successors"][-1]["accepted_commit"] = "0" * 40
        self._reject(c, "PC0-POST-NCE-UNACCEPTED-COMMIT")

    def test_wrong_accepted_authority_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][1]["successors"][-1]["accepted_authority"] = "unauthorized"
        self._reject(c, "PC0-POST-NCE-UNACCEPTED-AUTHORITY")

    def test_wrong_change_class_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][1]["successors"][-1]["change_class"] = "UNRELATED"
        self._reject(c, "PC0-POST-NCE-CHANGE-CLASS")

    def test_skipped_intermediate_successor_rejected(self):
        c = deepcopy(self.contract)
        del c["paths"][1]["successors"][1]
        self._reject(c, "PC0-POST-NCE-STEP-COUNT")

    def test_reordered_successor_rejected(self):
        c = deepcopy(self.contract)
        entries = c["paths"][1]["successors"]
        entries[0], entries[1] = entries[1], entries[0]
        self._reject(c, "PC0-POST-NCE-BROKEN-CHAIN")

    def test_historical_nce_digest_rewrite_rejected(self):
        c = deepcopy(self.contract)
        nce = next(p for p in c["paths"] if "xafpay_v2" in p["path"])
        nce["historical_anchor_sha256"] = "0" * 64
        self._reject(c, "PC0-POST-NCE-ANCHOR-CHANGED")

    def test_historical_pc8_anchor_cannot_be_replaced(self):
        c = deepcopy(self.contract)
        item = next(p for p in c["paths"] if "tenant_middleware" in p["path"])
        entry = next(x for x in item["successors"] if x["accepted_commit"].startswith("5931c"))
        entry["successor_sha256"] = "0" * 64
        self._reject(c, "PC0-POST-NCE-SOURCE-HASH")

    def test_historical_anchor_contract_rewrite_rejected(self):
        c = deepcopy(self.contract)
        c["paths"][0]["historical_anchor_contract"] = "unauthorized_baseline.json"
        self._reject(c, "PC0-POST-NCE-ANCHOR-CHANGED")

    def test_wrong_historical_anchor_commit_rejected(self):
        c = deepcopy(self.contract)
        original = c["paths"][0]["historical_anchor_commit"]
        c["paths"][0]["historical_anchor_commit"] = original[:-1] + (
            "0" if original[-1] != "0" else "1"
        )
        self._reject(c, "PC0-POST-NCE-ANCHOR-CHANGED")

    def test_extra_unaccepted_path_rejected(self):
        c = deepcopy(self.contract)
        fake = deepcopy(c["paths"][0])
        fake["path"] = "core/domain/finance/postings.py"
        c["paths"].append(fake)
        self._reject(c, "PC0-POST-NCE-SUCCESSOR-PATHS")

    def test_original_pc8_release_manifest_hash_cannot_be_rewritten(self):
        needed = [
            "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json",
            "contracts/platform/v1/pc8_release_manifest.json",
            "contracts/platform/v1/pc0_post_nce_source_successors.json",
            "core/middleware/auth_middleware.py",
            "core/middleware/tenant_middleware.py",
            "core/middleware/branch_middleware.py",
        ]
        with tempfile.TemporaryDirectory(prefix="pc0-pc8-historical-") as folder:
            candidate = Path(folder)
            for rel in needed:
                output = candidate / rel
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, output)
            self.assertEqual(3, len(_pc8_composition_replacements(candidate)))
            manifest = candidate / "contracts/platform/v1/pc8_release_manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            entry = next(x for x in data["artifacts"]
                         if x["path"] == "core/middleware/auth_middleware.py")
            entry["sha256"] = "0" * 64
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(PC0ArchitectureError, "PC0-PC8-HISTORICAL-FINGERPRINT"):
                _pc8_composition_replacements(candidate)

    def test_post_registration_source_mutation_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory(prefix="pc0-successor-source-") as d:
            r = Path(d)
            dest = r / "contracts/platform/v1/pc0_post_nce_source_successors.json"
            dest.parent.mkdir(parents=True)
            shutil.copyfile(REGISTRY, dest)
            source_path = "settings.py"
            target = r / source_path
            shutil.copyfile(ROOT / source_path, target)
            anchor = _POST_NCE_TRUSTED[source_path]["anchor"]
            self.assertEqual(_source_sha256(target), _post_nce_resolved_hash(r, source_path, anchor))
            target.write_text(target.read_text(encoding="utf-8") + "\n# altered\n", encoding="utf-8")
            self.assertIsNone(_post_nce_resolved_hash(r, source_path, anchor))

    def test_current_authority_not_laundered_into_previously_accepted_chain(self):
        # PC0-R2 validator source is *not* accepted by PCR yet.
        prior = next(p for p in self.contract["paths"]
                     if p["path"] == "core/platform/architecture_contract.py")
        self.assertEqual(prior["successors"][-1]["accepted_commit"],
                         "47200c29b974e1c89af2080139b8b899d0778898")
        self.assertNotEqual(_source_sha256(ROOT / prior["path"]),
                            prior["successors"][-1]["successor_sha256"])


if __name__ == "__main__":
    unittest.main()
