"""Executable PC0 modular-monolith and authority-boundary contract.

This module is deliberately standard-library only.  Importing or running it does
not import the application, open a database connection, or execute startup code.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from core.platform.release_integrity import canonical_sha256


CONTRACT_DIRECTORY = Path("contracts/platform/v1")
CONTRACT_FILES = {
    "module_map": "pc0_module_map.json",
    "dependency_policy": "pc0_dependency_policy.json",
    "interfaces": "pc0_public_private_interfaces.json",
    "authorities": "pc0_data_authority_register.json",
    "reference_migrations": "pc0_reference_authority_migration_register.json",
    "legacy_exceptions": "pc0_legacy_exception_baseline.json",
    "composition": "pc0_composition_baseline.json",
    "finance": "pc0_frozen_finance_baseline.json",
    "finance_inventory": "pc0_frozen_finance_inventory.json",
    "pc1": "pc1_structural_authority.json",
    "pc2": "pc2_party_authority.json",
    "pc3": "pc3_semantic_authority.json",
    "pc4": "pc4_operating_context_authority.json",
    "pc5": "pc5_identity_policy_audit_authority.json",
    "kernel": "pc0_kernel_boundaries.json",
}
ROOT_PYTHON_MODULES = {
    "app", "container", "database", "logging_config", "main", "settings", "startup"
}
H1B_SUCCESSOR_FILE = "pc0_h1b_composition_successor.json"
_H1B_SCHEMA = "xbos.platform.pc0-h1b-composition-successor.v1"
_H1B_AUTHORITY = "XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION"
_H1B_CLASS = "POSTHOC_PC0_COMPOSITION_AND_NON_FINANCE_EXTENSION_SUCCESSOR_ONLY"
_H1B_SOURCE_BASE = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
_H1B_STARTUP_HISTORICAL = "465fb8e613f66de8f77b7a3d4b4566c42dda1ad5db9435608a66cfa2fb20e698"
_H1B_STARTUP_SUCCESSOR = "fde45446f8f85df518e1997a5b5005308f6314ed4088a582a7fefeb6eee90dce"
_H1B_EXTENSION_HASHES = {
    "sql/cch_customer_channel_checkout_authority_up.sql": "a8e9663911a11c1b3df9dea462ceb20ca6598329baf1144af2f9f50fa937a3fb",
    "sql/cch_customer_channel_checkout_authority_down.sql": "4344980ab4d8821076185a1987c6cb0df744d3ccc782138923a844708af10c01",
    "versions/cch_customer_channel_checkout_authority_047.py": "8f9b6ca94353c6fe83843a37ae1e4be619442debfdf55a12f460a16dc57d6859",
}
_H1B_PC0_RELEASE_HISTORICAL = {
    "core/platform/architecture_contract.py": "eae3265ad7632fcb9bc811ccda290579d59583ebc15aaf8d762a7262c93755b8",
    "tests/contracts/test_pc0_kernel_boundaries.py": "ece19ea243bc1725ebf0e7446af69c28ff83411cd2ff0f2cf717a9de842d06f9",
}

_NCE_AUTHORITY = "XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION"
_NCE_COMMIT = "92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611"
_NCE_TAG = "xbos-nce-r1-r1-e2-r1-xafpay-v2-event-consumer-accepted-20260923"
_NCE_COMMON_PARENT = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
_NCE_KERNEL_ROUTER_HISTORICAL = "e3bd3ee9be4006337ecb07eb53f61fb01838c2d952f915c3361481d0fd109d7f"
_NCE_KERNEL_ROUTER_SUCCESSOR = "a8b4a8b645ed7dd31367eb4dfa5643118ae7e518370817fdd5ddba997dd21c3d"
_NCE_SOURCE_ROOT = "core/integrations/xafpay_v2"
_NCE_SOURCE_HASHES = {
    "core/integrations/xafpay_v2/__init__.py": "81a784b6db2386847bab5b0a86633d85ae57986e76c003dd11e46dd5dd7fc38a",
    "core/integrations/xafpay_v2/contract.py": "8bb5e87bbd49d94b0a45499ca544c0f21964e84f867d3c9389c24afe8b54fb5f",
    "core/integrations/xafpay_v2/repository.py": "da0065acac20914b5f90063b9f72315aba41f06d15639ebd1b4e0cdbccaea8a8",
    "core/integrations/xafpay_v2/router.py": "21801c3bec26128b19426edab6066448fd98f72bc4ac56b7d477f27441b10e84",
    "core/integrations/xafpay_v2/service.py": "5af5e6484fd03bbfe843c1d21c3c01094d3166ff179ba3f8bbcf77f3f006cc51",
}
_NCE_AUTHORIZED_EDGES = {
    ("core/api/kernel_router.py", "core.integrations.xafpay_v2.router", "composition", "xafpay"),
    ("core/integrations/xafpay_v2/router.py", "database", "xafpay", "application"),
}



POST_NCE_SOURCE_SUCCESSORS_FILE = "pc0_post_nce_source_successors.json"
_POST_NCE_SUCCESSOR_SCHEMA = "xbos.platform.pc0-post-nce-accepted-source-successors.v1"
_POST_NCE_SUCCESSOR_AUTHORITY = "XBOS-NEUTRAL-F-R1-B1-R1-PC0-R2"
_POST_NCE_ACCEPTED_CUTOFF = "47200c29b974e1c89af2080139b8b899d0778898"
# Every accepted SHA is pinned independently of the additive registry.
# This is a closed list of observed Git commits, never a current-hash acceptor.
_POST_NCE_TRUSTED = {'core/integrations/xafpay_v2/contract.py': {'anchor': '8bb5e87bbd49d94b0a45499ca544c0f21964e84f867d3c9389c24afe8b54fb5f',
                                             'commits': [('81769368cf2fa9b2dc752362623cbfc9f64be21d',
                                                          'XBOS-NEUTRAL-F-R1-B1-R1-N2-R2',
                                                          '4cccb50f0f44dd32d63012849fb12df8a6eec5ea2fc7dd3b0637736227c8b486')]},
 'core/middleware/auth_middleware.py': {'anchor': '4a8cafe8e87069499da4ee798ba060e54b757224930e131a434f8b99f18e2366',
                                        'commits': [('92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611',
                                                     'XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION',
                                                     'f6dba4aff0700825ec393963bcb627f47dcb01c49e90a872898d82013c0638ab'),
                                                    ('d064f617489febfa95a6bab43cb96a9a8125dedd',
                                                     'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                     'c96998d7badd9516db03bd2c6435ad46af3ccc704b0073794878d4921eb77c35'),
                                                    ('5931c901413af296c156af593ff3187b75006d5b',
                                                     'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                     'abe47c31cd1bf7582671c11d677c67b2fefd76001601eb38020983c73f98fb08'),
                                                    ('51057262faf7288e0ba4a8d488c8f2ff94e5cbe0',
                                                     'XBOS-NEUTRAL-F-R1-B1-C2',
                                                     'e03e258e5ebb574445b3a29e4db950f6ef80dde7b8fc344b45d7f781dc64b8d4')]},
 'core/middleware/branch_middleware.py': {'anchor': 'af0c6cc09242d60f54c7d300e5fadda872b13db2e793307afedf47036bd5554f',
                                          'commits': [('92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611',
                                                       'XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION',
                                                       '2fe968cfc640a5029a2fb57cec922dbdc35773c5eeb1d48d10f5ea0c9b91c1aa'),
                                                      ('d064f617489febfa95a6bab43cb96a9a8125dedd',
                                                       'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                       'd395fc467c6ae3242d21e7e4aea8dfdb0e38824545c065704572e5b96323dc66'),
                                                      ('5931c901413af296c156af593ff3187b75006d5b',
                                                       'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                       '64d498a2644c15e10221edbcc43b499218d9f405c3823e19b7dc321998994c5e'),
                                                      ('51057262faf7288e0ba4a8d488c8f2ff94e5cbe0',
                                                       'XBOS-NEUTRAL-F-R1-B1-C2',
                                                       'a53ed3985c29ce3e51c6e885f9d9b6b0746fc892b794b0478ffccfd5a42155a5'),
                                                      ('b9174cbe07a81808900f16c91f3ba229630cd680',
                                                       'XBOS-NEUTRAL-F-R1-B1-R1',
                                                       '568d8f7ee0f1bec31d5e46ca2386b093f23a25886a390680cc4d825fd5b3dfa4')]},
 'core/middleware/tenant_middleware.py': {'anchor': '5151239379e4b6e686bc168818d655c94e2945df324ee5452441549deb83dd9d',
                                          'commits': [('92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611',
                                                       'XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION',
                                                       'ac93413f68256aac2cbaf88bce30ae738e478dfb1e1339da5694ec625360611d'),
                                                      ('d064f617489febfa95a6bab43cb96a9a8125dedd',
                                                       'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                       '2d30b184ea4f83860868f0c87db5326d9a424a5ac0e794f8110a0cbee1964cd3'),
                                                      ('5931c901413af296c156af593ff3187b75006d5b',
                                                       'XBOS-G02-C3-H1B-R2-R1-PC0-PC6-SUCCESSOR-REPAIR-AND-FULL-REGRESSION',
                                                       'dda4211df3a6cd4e0e07a2daf9590722b0717937348bebcd4d426b463dbc1101'),
                                                      ('51057262faf7288e0ba4a8d488c8f2ff94e5cbe0',
                                                       'XBOS-NEUTRAL-F-R1-B1-C2',
                                                       'e7218132823dce924c0f8fa62cebcf0cd584f169e0fd15e15b3790bf2f7657a9'),
                                                      ('b9174cbe07a81808900f16c91f3ba229630cd680',
                                                       'XBOS-NEUTRAL-F-R1-B1-R1',
                                                       'db8ea71d0205fbf6b40b8e857d20d12f8584283a40441a2df49869c10394d0ff')]},
 'core/platform/architecture_contract.py': {'anchor': '5345e6655603ae89416568a4548dc798289f2b1702fe066cf51c29e90df64d7b',
                                            'commits': [('47200c29b974e1c89af2080139b8b899d0778898',
                                                         'XBOS-NEUTRAL-F-R1-B1-R1-PC0-R1',
                                                         'bbd1de7d9f19853d651ce81251f411b2b206e3557f927e6451881ef6fb6d82c6')]},
 'settings.py': {'anchor': '38befbb010086c27a0a6612643340e8a5f761133282b27f5fb92336b5e05476f',
                 'commits': [('b9174cbe07a81808900f16c91f3ba229630cd680',
                              'XBOS-NEUTRAL-F-R1-B1-R1',
                              '23952c58c849c9acfe74aeaf72503ac08910fb35713c6d0d269b9b34cec595ad')]}}


_POST_NCE_TRUSTED_ORIGINS = {
    "settings.py": ("pc0_composition_baseline.json", "9ce8c1a5746ec7607636d6a9be20102194e9f230"),
    "core/middleware/auth_middleware.py": ("pc0_composition_baseline.json", "227459dd32f54e3acc1df80b50ddf4c424a4a48e"),
    "core/middleware/tenant_middleware.py": ("pc0_composition_baseline.json", "4fe677b50aa34d98fa122974f0ce36dae76cd767"),
    "core/middleware/branch_middleware.py": ("pc0_composition_baseline.json", "4fe677b50aa34d98fa122974f0ce36dae76cd767"),
    "core/integrations/xafpay_v2/contract.py": (
        "pc0_h1b_composition_successor.json#nce_additive_successor.module_overlay",
        "92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611",
    ),
    "core/platform/architecture_contract.py": (
        "pc0_h1b_composition_successor.json#pc0_release_replacements",
        "5931c901413af296c156af593ff3187b75006d5b",
    ),
}
_POST_NCE_TRUSTED_PC8_ACCEPTED = {
    "core/middleware/auth_middleware.py": "abe47c31cd1bf7582671c11d677c67b2fefd76001601eb38020983c73f98fb08",
    "core/middleware/tenant_middleware.py": "dda4211df3a6cd4e0e07a2daf9590722b0717937348bebcd4d426b463dbc1101",
    "core/middleware/branch_middleware.py": "64d498a2644c15e10221edbcc43b499218d9f405c3823e19b7dc321998994c5e",
}
_POST_NCE_TRUSTED_CHANGE_CLASSES = {
    "92f6dbc7db37": "NCE_RESTORATION",
    "d064f617489f": "H1B_COMPOSITION",
    "5931c901413a": "H1B_COMPOSITION",
    "51057262faf7": "VN0_C2_BROWSER_COMPOSITION",
    "b9174cbe07a8": "VN0_R1_STANDALONE_AUTH_CONFIG",
    "81769368cf2f": "N2_R2_TERMINOLOGY_ONLY",
    "47200c29b974": "PC0_R1_ACCEPTED_CONTRACT_REPAIR",
}


def _validate_post_nce_source_successors(
    root: Path, proposed: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Validate every step in each accepted file lineage, against frozen SHA pins."""
    contract_path = root / CONTRACT_DIRECTORY / POST_NCE_SOURCE_SUCCESSORS_FILE
    if proposed is None:
        if not contract_path.is_file():
            return {}
        proposed = _load_json(root, POST_NCE_SOURCE_SUCCESSORS_FILE)
    if not isinstance(proposed, dict) or set(proposed) != {
        "schema", "authority", "accepted_cutoff_commit", "paths"
    }:
        _fail("PC0-POST-NCE-SUCCESSOR-SHAPE", str(proposed))
    if (
        proposed["schema"] != _POST_NCE_SUCCESSOR_SCHEMA
        or proposed["authority"] != _POST_NCE_SUCCESSOR_AUTHORITY
        or proposed["accepted_cutoff_commit"] != _POST_NCE_ACCEPTED_CUTOFF
    ):
        _fail("PC0-POST-NCE-SUCCESSOR-AUTHORITY", "unrecognized registry identity")
    declarations = proposed["paths"]
    if not isinstance(declarations, list):
        _fail("PC0-POST-NCE-SUCCESSOR-PATHS", "paths must be a list")
    indexed = {item.get("path"): item for item in declarations if isinstance(item, dict)}
    if len(indexed) != len(declarations) or set(indexed) != set(_POST_NCE_TRUSTED):
        _fail("PC0-POST-NCE-SUCCESSOR-PATHS", str(sorted(indexed)))
    final: dict[str, str] = {}
    for path, trusted in _POST_NCE_TRUSTED.items():
        item = indexed[path]
        if set(item) != {
            "path", "historical_anchor_contract", "historical_anchor_commit",
            "historical_anchor_sha256", "successors"
        }:
            _fail("PC0-POST-NCE-SUCCESSOR-PATH", path)
        anchor = item["historical_anchor_sha256"]
        expected_origin, expected_commit_prefix = _POST_NCE_TRUSTED_ORIGINS[path]
        if (
            anchor != trusted["anchor"]
            or item["historical_anchor_contract"] != expected_origin
            or not isinstance(item["historical_anchor_commit"], str)
            or item["historical_anchor_commit"] != expected_commit_prefix
        ):
            _fail("PC0-POST-NCE-ANCHOR-CHANGED", path)
        steps = item["successors"]
        if not isinstance(steps, list) or len(steps) != len(trusted["commits"]):
            _fail("PC0-POST-NCE-STEP-COUNT", path)
        predecessor = anchor
        for index, (entry, expected_step) in enumerate(zip(steps, trusted["commits"])):
            if not isinstance(entry, dict) or set(entry) != {
                "path", "predecessor_sha256", "successor_sha256",
                "accepted_commit", "accepted_authority", "change_class",
            }:
                _fail("PC0-POST-NCE-STEP-SHAPE", f"{path}@{index}")
            commit, authority, digest = expected_step
            if entry["path"] != path:
                _fail("PC0-POST-NCE-STEP-PATH", f"{path}@{index}")
            if entry["predecessor_sha256"] != predecessor:
                _fail("PC0-POST-NCE-BROKEN-CHAIN", f"{path}@{index}")
            if entry["accepted_commit"] != commit:
                _fail("PC0-POST-NCE-UNACCEPTED-COMMIT", f"{path}@{index}")
            if entry["accepted_authority"] != authority:
                _fail("PC0-POST-NCE-UNACCEPTED-AUTHORITY", f"{path}@{index}")
            if entry["successor_sha256"] != digest:
                _fail("PC0-POST-NCE-SOURCE-HASH", f"{path}@{index}")
            classification = next(
                (label for prefix, label in _POST_NCE_TRUSTED_CHANGE_CLASSES.items()
                 if commit.startswith(prefix)),
                None,
            )
            if entry["change_class"] != classification or classification is None:
                _fail("PC0-POST-NCE-CHANGE-CLASS", f"{path}@{index}")
            predecessor = digest
        final[path] = predecessor
    return final


def _post_nce_resolved_hash(root: Path, path: str, historical: str) -> str | None:
    """Only a continuous, pinned chain from historical to final is permitted."""
    finals = _validate_post_nce_source_successors(root)
    trusted = _POST_NCE_TRUSTED.get(path)
    if not trusted:
        return None
    sequence = [trusted["anchor"]] + [step[2] for step in trusted["commits"]]
    if historical not in sequence[:-1]:
        return None
    source_path = root / path
    if not source_path.is_file() or _source_sha256(source_path) != finals[path]:
        return None
    return finals[path]


class PC0ArchitectureError(AssertionError):
    """A deterministic PC0 contract violation."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ImportEdge:
    source_path: str
    import_name: str
    source_module: str
    target_module: str

    def key(self) -> tuple[str, str, str, str]:
        return (self.source_path, self.import_name, self.source_module, self.target_module)


def _fail(code: str, detail: str) -> None:
    raise PC0ArchitectureError(code, detail)


def _load_json(root: Path, name: str) -> dict[str, Any]:
    path = root / CONTRACT_DIRECTORY / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-CONTRACT-READ", f"{path.as_posix()}: {exc}")


def _sha256_file(path: Path) -> str:
    return canonical_sha256(path)


def _source_sha256(path: Path) -> str:
    """Hash the canonical Git text, independent of checkout newline policy."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


VN0_BROWSER_SUCCESSOR_FILE = "pc0_vn0_browser_session_successor.json"
_VN0_BROWSER_SUCCESSOR_SCHEMA = "xbos.platform.pc0-vn0-browser-session-composition-successor.v1"
_VN0_BROWSER_AUTHORITY = "XBOS-NEUTRAL-F-R1-B1-R1-PC0-R1"
_VN0_BROWSER_CLASS = "ADDITIVE_VN0_C2_BROWSER_SESSION_KERNEL_COMPOSITION"
_VN0_C2_COMMIT = "51057262faf7288e0ba4a8d488c8f2ff94e5cbe0"
_VN0_C2_KERNEL_SHA256 = "243a6f77c8804eaff82cb131f8edc5d6dcd24e47ecafd6fa7f8ae660f2d97b00"
_VN0_BROWSER_MARKERS = [
    "from core.auth.browser_session_router import router as browser_session_router",
    "kernel_router.include_router(browser_session_router)",
]
_VN0_NCE_MARKERS = [
    "from core.integrations.xafpay_v2.router import router as xafpay_v2_router",
    'prefix="/integrations/xafpay-v2"',
]


def _validate_vn0_browser_successor(
    root: Path, contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Pin the accepted C2 composition without rewriting historical NCE truth."""
    path = root / CONTRACT_DIRECTORY / VN0_BROWSER_SUCCESSOR_FILE
    if contract is None:
        if not path.is_file():
            return None
        try:
            contract = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _fail("PC0-VN0-SUCCESSOR-READ", str(exc))
    if not isinstance(contract, dict) or set(contract) != {
        "schema", "authority", "successor_class", "historical_nce", "vn0_c2",
    }:
        _fail("PC0-VN0-SUCCESSOR-SHAPE", str(contract))
    if (
        contract["schema"] != _VN0_BROWSER_SUCCESSOR_SCHEMA
        or contract["authority"] != _VN0_BROWSER_AUTHORITY
        or contract["successor_class"] != _VN0_BROWSER_CLASS
    ):
        _fail("PC0-VN0-SUCCESSOR-AUTHORITY", "schema, authority or class mismatch")
    nce = contract["historical_nce"]
    if nce != {
        "authority": _NCE_AUTHORITY,
        "commit": _NCE_COMMIT,
        "kernel_sha256": _NCE_KERNEL_ROUTER_SUCCESSOR,
    }:
        _fail("PC0-VN0-NCE-HISTORY-CHANGED", str(nce))
    c2 = contract["vn0_c2"]
    if not isinstance(c2, dict) or set(c2) != {
        "accepted_commit", "kernel_path", "successor_sha256",
        "required_markers", "preserved_nce_markers",
    }:
        _fail("PC0-VN0-C2-SUCCESSOR-SHAPE", str(c2))
    if (
        c2["accepted_commit"] != _VN0_C2_COMMIT
        or c2["kernel_path"] != "core/api/kernel_router.py"
        or c2["successor_sha256"] != _VN0_C2_KERNEL_SHA256
    ):
        _fail("PC0-VN0-C2-SUCCESSOR-IDENTITY", str(c2))
    if c2["required_markers"] != _VN0_BROWSER_MARKERS:
        _fail("PC0-VN0-C2-BROWSER-MARKERS", str(c2["required_markers"]))
    if c2["preserved_nce_markers"] != _VN0_NCE_MARKERS:
        _fail("PC0-VN0-C2-NCE-MARKERS", str(c2["preserved_nce_markers"]))
    source_path = root / c2["kernel_path"]
    if _source_sha256(source_path) != _VN0_C2_KERNEL_SHA256:
        _fail("PC0-VN0-C2-KERNEL-CHANGED", c2["kernel_path"])
    source = source_path.read_text(encoding="utf-8")
    for marker in _VN0_BROWSER_MARKERS:
        if marker not in source:
            _fail("PC0-VN0-C2-BROWSER-MARKER-MISSING", marker)
    for marker in _VN0_NCE_MARKERS:
        if marker not in source:
            _fail("PC0-VN0-C2-NCE-MARKER-MISSING", marker)
    return contract


def _validate_h1b_successor_contract(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema", "authority", "successor_class", "source_base",
        "historical_pc0_composition_baseline_mutated",
        "historical_pc0_finance_inventory_mutated",
        "historical_pc0_release_manifest_mutated",
        "composition_override", "non_finance_extensions", "migration",
        "pc0_release_replacements", "allowed_paths", "nce_additive_successor",
    }
    if set(contract) != expected_keys:
        _fail("PC0-H1B-SUCCESSOR-SHAPE", f"keys={sorted(contract)}")
    if contract.get("schema") != _H1B_SCHEMA:
        _fail("PC0-H1B-SUCCESSOR-SCHEMA", str(contract.get("schema")))
    if contract.get("authority") != _H1B_AUTHORITY or contract.get("successor_class") != _H1B_CLASS:
        _fail("PC0-H1B-SUCCESSOR-AUTHORITY", "authority or successor class mismatch")
    if contract.get("source_base") != _H1B_SOURCE_BASE:
        _fail("PC0-H1B-SUCCESSOR-BASE", str(contract.get("source_base")))
    for key in (
        "historical_pc0_composition_baseline_mutated",
        "historical_pc0_finance_inventory_mutated",
        "historical_pc0_release_manifest_mutated",
    ):
        if contract.get(key) is not False:
            _fail("PC0-H1B-HISTORICAL-REWRITE", key)

    nce = contract.get("nce_additive_successor")
    expected_nce_keys = {
        "authority", "nce_commit", "nce_tag", "common_parent",
        "kernel_router_override", "module_overlay", "authorized_dependency_edges",
    }
    if not isinstance(nce, dict) or set(nce) != expected_nce_keys:
        _fail("PC0-NCE-SUCCESSOR-SHAPE", str(nce))
    if (
        nce.get("authority") != _NCE_AUTHORITY
        or nce.get("nce_commit") != _NCE_COMMIT
        or nce.get("nce_tag") != _NCE_TAG
        or nce.get("common_parent") != _NCE_COMMON_PARENT
    ):
        _fail("PC0-NCE-SUCCESSOR-AUTHORITY", "accepted NCE identity mismatch")
    kernel = nce.get("kernel_router_override")
    if not isinstance(kernel, dict) or set(kernel) != {
        "path", "historical_sha256", "successor_sha256", "required_markers"
    }:
        _fail("PC0-NCE-KERNEL-OVERRIDE", "invalid shape")
    if (
        kernel.get("path") != "core/api/kernel_router.py"
        or kernel.get("historical_sha256") != _NCE_KERNEL_ROUTER_HISTORICAL
        or kernel.get("successor_sha256") != _NCE_KERNEL_ROUTER_SUCCESSOR
        or kernel.get("required_markers") != [
            "from core.integrations.xafpay_v2.router import router as xafpay_v2_router",
            'prefix="/integrations/xafpay-v2"',
        ]
    ):
        _fail("PC0-NCE-KERNEL-OVERRIDE", str(kernel))
    if _source_sha256(root / "core/api/kernel_router.py") != _NCE_KERNEL_ROUTER_SUCCESSOR:
        if _validate_vn0_browser_successor(root) is None:
            _fail("PC0-NCE-KERNEL-CHANGED", "core/api/kernel_router.py")
    kernel_source = (root / "core/api/kernel_router.py").read_text(encoding="utf-8")
    for marker in kernel["required_markers"]:
        if marker not in kernel_source:
            _fail("PC0-NCE-KERNEL-MARKER", marker)
    overlay = nce.get("module_overlay")
    if not isinstance(overlay, dict) or set(overlay) != {"module_code", "source_root", "files"}:
        _fail("PC0-NCE-MODULE-OVERLAY", "invalid shape")
    if overlay.get("module_code") != "xafpay" or overlay.get("source_root") != _NCE_SOURCE_ROOT:
        _fail("PC0-NCE-MODULE-OVERLAY", str(overlay))
    files = overlay.get("files")
    if not isinstance(files, list):
        _fail("PC0-NCE-MODULE-OVERLAY", "files missing")
    by_path = {item.get("path"): item for item in files if isinstance(item, dict)}
    if len(by_path) != len(files) or set(by_path) != set(_NCE_SOURCE_HASHES):
        _fail("PC0-NCE-SOURCE-FILES", str(sorted(by_path)))
    for relative, expected_hash in _NCE_SOURCE_HASHES.items():
        item = by_path[relative]
        if set(item) != {"path", "sha256"} or item.get("sha256") != expected_hash:
            _fail("PC0-NCE-SOURCE-FILES", relative)
        actual_overlay = _source_sha256(root / relative)
        if actual_overlay != expected_hash:
            accepted = _post_nce_resolved_hash(root, relative, expected_hash)
            if accepted != actual_overlay:
                _fail("PC0-NCE-SOURCE-CHANGED", relative)
    edges = nce.get("authorized_dependency_edges")
    if not isinstance(edges, list):
        _fail("PC0-NCE-DEPENDENCY-EDGES", "missing")
    edge_set = {
        (
            item.get("source_path"), item.get("import_name"),
            item.get("source_module"), item.get("target_module"),
        )
        for item in edges if isinstance(item, dict)
    }
    if len(edge_set) != len(edges) or edge_set != _NCE_AUTHORIZED_EDGES:
        _fail("PC0-NCE-DEPENDENCY-EDGES", str(sorted(edge_set)))

    composition = contract.get("composition_override")
    if not isinstance(composition, dict) or set(composition) != {
        "path", "historical_sha256", "successor_sha256", "required_markers"
    }:
        _fail("PC0-H1B-COMPOSITION-OVERRIDE", "invalid shape")
    if composition.get("path") != "startup.py":
        _fail("PC0-H1B-COMPOSITION-OVERRIDE", str(composition.get("path")))
    if composition.get("historical_sha256") != _H1B_STARTUP_HISTORICAL:
        _fail("PC0-H1B-COMPOSITION-HISTORICAL", str(composition.get("historical_sha256")))
    if composition.get("successor_sha256") != _H1B_STARTUP_SUCCESSOR:
        _fail("PC0-H1B-COMPOSITION-SUCCESSOR", str(composition.get("successor_sha256")))
    markers = composition.get("required_markers")
    expected_markers = [
        "from restaurant.customer_channel.router import router as customer_channel_router",
        "app.include_router(customer_channel_router)",
    ]
    if markers != expected_markers:
        _fail("PC0-H1B-COMPOSITION-MARKERS", str(markers))
    startup = root / "startup.py"
    if _source_sha256(startup) != _H1B_STARTUP_SUCCESSOR:
        _fail("PC0-H1B-COMPOSITION-CHANGED", "startup.py")
    source = startup.read_text(encoding="utf-8")
    for marker in expected_markers:
        if marker not in source:
            _fail("PC0-H1B-COMPOSITION-MARKER", marker)

    extensions = contract.get("non_finance_extensions")
    if not isinstance(extensions, list) or len(extensions) != 3:
        _fail("PC0-H1B-EXTENSIONS", "exactly three extensions required")
    by_path: dict[str, dict[str, Any]] = {}
    for item in extensions:
        if not isinstance(item, dict) or set(item) != {"owner", "root", "path", "sha256", "reason"}:
            _fail("PC0-H1B-EXTENSIONS", str(item))
        path = item.get("path")
        if path in by_path:
            _fail("PC0-H1B-EXTENSIONS", f"duplicate={path}")
        by_path[path] = item
    if set(by_path) != set(_H1B_EXTENSION_HASHES):
        _fail("PC0-H1B-EXTENSIONS", f"paths={sorted(by_path)}")
    for relative, expected_hash in _H1B_EXTENSION_HASHES.items():
        item = by_path[relative]
        if (
            item.get("owner") != "H1B_CUSTOMER_CHANNEL"
            or item.get("root") != "alembic_neutral"
            or item.get("sha256") != expected_hash
            or item.get("reason") != "H1B_CUSTOMER_CHANNEL_NON_FINANCE_SCHEMA_EXTENSION"
        ):
            _fail("PC0-H1B-EXTENSIONS", relative)
        if _source_sha256(root / "alembic_neutral" / relative) != expected_hash:
            _fail("PC0-NON-FINANCE-EXTENSION-CHANGED", f"alembic_neutral/{relative}")

    migration = contract.get("migration")
    if migration != {
        "revision": "cch_customer_channel_checkout_authority_047",
        "parent": "r1_restaurant_order_line_lifecycle_046",
        "new_table_count": 2,
        "financial_effect": "ZERO",
    }:
        _fail("PC0-H1B-MIGRATION-SUCCESSOR", str(migration))

    replacements = contract.get("pc0_release_replacements")
    if not isinstance(replacements, list) or len(replacements) != 2:
        _fail("PC0-H1B-RELEASE-REPLACEMENTS", "exactly two replacements required")
    replacement_by_path = {item.get("path"): item for item in replacements if isinstance(item, dict)}
    if set(replacement_by_path) != set(_H1B_PC0_RELEASE_HISTORICAL):
        _fail("PC0-H1B-RELEASE-REPLACEMENTS", f"paths={sorted(replacement_by_path)}")
    for relative, historical in _H1B_PC0_RELEASE_HISTORICAL.items():
        item = replacement_by_path[relative]
        if set(item) != {"path", "historical_sha256", "successor_sha256"}:
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", relative)
        actual = _source_sha256(root / relative)
        accepted = _post_nce_resolved_hash(root, relative, item.get("successor_sha256"))
        if accepted != actual and relative == _PC0_R3_SEALED_SOURCE_PATH:
            accepted = _pc0_r3_sealed_successor(root, relative, item.get("successor_sha256"))
        if item.get("historical_sha256") != historical or (
            item.get("successor_sha256") != actual and accepted != actual
        ):
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", relative)

    allowed = contract.get("allowed_paths")
    expected_allowed = sorted({
        "startup.py",
        "core/api/kernel_router.py",
        *_NCE_SOURCE_HASHES,
        *(f"alembic_neutral/{path}" for path in _H1B_EXTENSION_HASHES),
        *_H1B_PC0_RELEASE_HISTORICAL,
    })
    if allowed != expected_allowed:
        _fail("PC0-H1B-ALLOWED-PATHS", str(allowed))
    return contract


def _load_h1b_successor(root: Path) -> dict[str, Any] | None:
    path = root / CONTRACT_DIRECTORY / H1B_SUCCESSOR_FILE
    if not path.is_file():
        return None
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-H1B-SUCCESSOR-READ", str(exc))
    return _validate_h1b_successor_contract(root, contract)


def _pc8_composition_replacements(root: Path) -> dict[str, tuple[str, str]]:
    contract_path = root / CONTRACT_DIRECTORY / "pc8_h1b_private_route_admission_successor.json"
    manifest_path = root / CONTRACT_DIRECTORY / "pc8_release_manifest.json"
    if not contract_path.is_file() and not manifest_path.is_file():
        return {}
    if not contract_path.is_file() or not manifest_path.is_file():
        _fail("PC0-PC8-SUCCESSOR-INCOMPLETE", "contract/manifest pair required")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("PC0-PC8-SUCCESSOR-READ", str(exc))
    if (
        contract.get("schema") != "xbos.platform.pc8-h1b-private-route-admission-successor.v1"
        or contract.get("source_base") != _H1B_SOURCE_BASE
        or contract.get("private_prefix") != "/internal/customer-channel/v1"
        or contract.get("new_platform_business_authority") is not False
        or contract.get("new_platform_schema_authority") is not False
    ):
        _fail("PC0-PC8-SUCCESSOR-AUTHORITY", "private-route successor mismatch")
    expected = {
        "core/middleware/auth_middleware.py": "4a8cafe8e87069499da4ee798ba060e54b757224930e131a434f8b99f18e2366",
        "core/middleware/tenant_middleware.py": "5151239379e4b6e686bc168818d655c94e2945df324ee5452441549deb83dd9d",
        "core/middleware/branch_middleware.py": "af0c6cc09242d60f54c7d300e5fadda872b13db2e793307afedf47036bd5554f",
    }
    bases = contract.get("accepted_base_canonical_sha256", {})
    artifacts = {item.get("path"): item.get("sha256") for item in manifest.get("artifacts", [])}
    replacements: dict[str, tuple[str, str]] = {}
    for relative, historical in expected.items():
        actual = _source_sha256(root / relative)
        pc8_digest = artifacts.get(relative)
        if pc8_digest != _POST_NCE_TRUSTED_PC8_ACCEPTED[relative]:
            _fail("PC0-PC8-HISTORICAL-FINGERPRINT", relative)
        if bases.get(relative) != historical:
            _fail("PC0-PC8-SUCCESSOR-INTEGRITY", relative)
        if pc8_digest != actual:
            accepted = _post_nce_resolved_hash(root, relative, pc8_digest)
            if not accepted or accepted != actual:
                _fail("PC0-PC8-SUCCESSOR-INTEGRITY", relative)
        replacements[relative] = (historical, actual)
    return replacements


_TRANSIENT_CACHE_COMPONENTS = {".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}


def _is_transient_runtime_artifact(relative: Path) -> bool:
    if relative.suffix.lower() in {".pyc", ".pyo"}:
        return True
    return any(part in _TRANSIENT_CACHE_COMPONENTS for part in relative.parts)



# Additive non-finance migration descendants: exact ten pre-accepted paths only.
_PC0_R3_AUTHORITY = "XBOS-NEUTRAL-F-R1-B1-R1-PC0-R3"
_PC0_R3_MIGRATIONS = {'sql/cc_catalog_binding_price_code_case_049_down.sql': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3B1-PRICE-CODE-CASE-PRESERVING-COMPATIBILITY-SUCCESSOR',
                                                         'accepted_commit': 'ca2b27bbc8a7c3c32b3a89c74623757da8c5e9c6',
                                                         'owner': 'XBOS_CUSTOMER_CHANNEL',
                                                         'reason': 'customer channel catalog binding or draft '
                                                                   'facade compatibility',
                                                         'revision': 'cc_catalog_binding_price_code_case_049',
                                                         'sha256': '562be581212789fb08ed9e688e5b28614b9cc8a27bc9df3150ff2dbe2aa2ad6b'},
 'sql/cc_catalog_binding_price_code_case_049_up.sql': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3B1-PRICE-CODE-CASE-PRESERVING-COMPATIBILITY-SUCCESSOR',
                                                       'accepted_commit': 'ca2b27bbc8a7c3c32b3a89c74623757da8c5e9c6',
                                                       'owner': 'XBOS_CUSTOMER_CHANNEL',
                                                       'reason': 'customer channel catalog binding or draft '
                                                                 'facade compatibility',
                                                       'revision': 'cc_catalog_binding_price_code_case_049',
                                                       'sha256': '6d8869ed0fd4d5647abe536441ba93e0759eab4e67089f21daca4a16e9959a4f'},
 'sql/cc_catalog_binding_registry_down.sql': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3A-CATALOG-BINDING-REGISTRY-SOURCE-AND-SCHEMA-MATERIALIZATION',
                                              'accepted_commit': 'a168df1de5041d3be2c32539e0d52544d1351ce0',
                                              'owner': 'XBOS_CUSTOMER_CHANNEL',
                                              'reason': 'customer channel catalog binding or draft facade '
                                                        'compatibility',
                                              'revision': 'cc_catalog_binding_registry_048',
                                              'sha256': '3228d3edcb83649abd0380b814de201ad3230bb54296d007cc24294387cc0ddb'},
 'sql/cc_catalog_binding_registry_up.sql': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3A-CATALOG-BINDING-REGISTRY-SOURCE-AND-SCHEMA-MATERIALIZATION',
                                            'accepted_commit': 'a168df1de5041d3be2c32539e0d52544d1351ce0',
                                            'owner': 'XBOS_CUSTOMER_CHANNEL',
                                            'reason': 'customer channel catalog binding or draft facade '
                                                      'compatibility',
                                            'revision': 'cc_catalog_binding_registry_048',
                                            'sha256': '5a0eb917b3ac3489c0d19e57f3e7567d29c09f44768d86094f1886b52a8df4c5'},
 'sql/cc_order_draft_facade_050_down.sql': {'accepted_authority': 'XAFPAY-XBOS-CC-ORDER-R1-PRIVATE-DRAFT-ORDER-FACADE-MATERIALIZATION',
                                            'accepted_commit': 'e0ae0123cec02cb2cb294e2bbad09df341be17c1',
                                            'owner': 'XBOS_CUSTOMER_CHANNEL',
                                            'reason': 'customer channel catalog binding or draft facade '
                                                      'compatibility',
                                            'revision': 'cc_order_draft_facade_050',
                                            'sha256': '9f396cd8c7972d8f6eab31b54bdad218826828a8daccbee8d65e390cad896916'},
 'sql/cc_order_draft_facade_050_up.sql': {'accepted_authority': 'XAFPAY-XBOS-CC-ORDER-R1-PRIVATE-DRAFT-ORDER-FACADE-MATERIALIZATION',
                                          'accepted_commit': 'e0ae0123cec02cb2cb294e2bbad09df341be17c1',
                                          'owner': 'XBOS_CUSTOMER_CHANNEL',
                                          'reason': 'customer channel catalog binding or draft facade '
                                                    'compatibility',
                                          'revision': 'cc_order_draft_facade_050',
                                          'sha256': 'bb7c8ac1b9d28618de243669efa5cb093472286a6c5d424d96c632a12dae6103'},
 'versions/browser_session_v1_051.py': {'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-C2',
                                        'accepted_commit': 'bbb60a1e979727917dc1b9f55d7f56e405b23d04',
                                        'owner': 'XBOS_PLATFORM_CORE',
                                        'reason': 'VN0 C2 browser-session registry; non-financial authority',
                                        'revision': 'browser_session_v1_051',
                                        'sha256': '9fd9dafbf4dbdba707090c3ced842659d3b6cb9436a112f3e1fd78b58fabe152'},
 'versions/cc_catalog_binding_price_code_case_049.py': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3B1-PRICE-CODE-CASE-PRESERVING-COMPATIBILITY-SUCCESSOR',
                                                        'accepted_commit': 'ca2b27bbc8a7c3c32b3a89c74623757da8c5e9c6',
                                                        'owner': 'XBOS_CUSTOMER_CHANNEL',
                                                        'reason': 'customer channel catalog binding or draft '
                                                                  'facade compatibility',
                                                        'revision': 'cc_catalog_binding_price_code_case_049',
                                                        'sha256': 'f31974da0d4dddc60519dbfa5f779ccb8f500f55158c6e4c1332dbb4951cebd8'},
 'versions/cc_catalog_binding_registry_048.py': {'accepted_authority': 'XAFPAY-XBOS-LOOP-B-R2-R3A-CATALOG-BINDING-REGISTRY-SOURCE-AND-SCHEMA-MATERIALIZATION',
                                                 'accepted_commit': 'a168df1de5041d3be2c32539e0d52544d1351ce0',
                                                 'owner': 'XBOS_CUSTOMER_CHANNEL',
                                                 'reason': 'customer channel catalog binding or draft facade '
                                                           'compatibility',
                                                 'revision': 'cc_catalog_binding_registry_048',
                                                 'sha256': 'ef557bd4a30e9a2a5e0a29e9ebd853935652aaf9ba3977cf5e38e8525d5a6dfb'},
 'versions/cc_order_draft_facade_050.py': {'accepted_authority': 'XAFPAY-XBOS-CC-ORDER-R1-PRIVATE-DRAFT-ORDER-FACADE-MATERIALIZATION',
                                           'accepted_commit': 'e0ae0123cec02cb2cb294e2bbad09df341be17c1',
                                           'owner': 'XBOS_CUSTOMER_CHANNEL',
                                           'reason': 'customer channel catalog binding or draft facade '
                                                     'compatibility',
                                           'revision': 'cc_order_draft_facade_050',
                                           'sha256': '360453965737470ad3a1c15f5a5b7465afe98b84df0a6471f83426f8397c41d5'}}
_PC0_R3_MIGRATION_REVISIONS = (
    "cc_catalog_binding_registry_048",
    "cc_catalog_binding_price_code_case_049",
    "cc_order_draft_facade_050",
    "browser_session_v1_051",
)


def _validate_pc0_r3_migration_extensions(
    root: Path, proposed: dict[str, Any] | None = None,
) -> dict[str, str]:
    if proposed is None:
        proposed = _load_json(root, "pc0_non_finance_migration_successors.json")
    if not isinstance(proposed, dict) or set(proposed) != {
        "schema", "authority", "root", "extensions",
    } or (
        proposed["schema"] != "xbos.platform.pc0-non-finance-migration-successors.v1"
        or proposed["authority"] != _PC0_R3_AUTHORITY
        or proposed["root"] != "alembic_neutral"
    ):
        _fail("PC0-R3-MIGRATION-AUTHORITY", "unexpected migration successor shape or owner")
    items = proposed["extensions"]
    if not isinstance(items, list) or len(items) != 10:
        _fail("PC0-R3-MIGRATION-COUNT", str(items))
    observed = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "path", "sha256", "accepted_commit", "accepted_authority", "revision",
            "owner", "reason",
        }:
            _fail("PC0-R3-MIGRATION-SHAPE", str(item))
        path = item["path"]
        if not isinstance(path, str) or "*" in path or "?" in path or "[" in path or path in observed:
            _fail("PC0-R3-MIGRATION-PATH", str(path))
        if path not in _PC0_R3_MIGRATIONS:
            _fail("PC0-R3-MIGRATION-UNREGISTERED", path)
        pinned = _PC0_R3_MIGRATIONS[path]
        if any(item[key] != pinned[key] for key in pinned):
            _fail("PC0-R3-MIGRATION-PROVENANCE", path)
        target = root / "alembic_neutral" / path
        if not target.is_file() or _source_sha256(target) != item["sha256"]:
            _fail("PC0-R3-MIGRATION-SOURCE-CHANGED", path)
        observed[path] = item["sha256"]
    if set(observed) != set(_PC0_R3_MIGRATIONS):
        _fail("PC0-R3-MIGRATION-MISSING", str(sorted(set(_PC0_R3_MIGRATIONS)-set(observed))))
    return observed


# N2 generic policy contract belongs to shared neutral Core, not Restaurant.
_PC0_R3_N2_MODULE = {'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-R1-N2',
 'accepted_commit': '631e9280bbf4d95d5c97400d3268a7cb9d787994',
 'authority': 'XBOS-NEUTRAL-F-R1-B1-R1-PC0-R3',
 'authority_split': {'concrete_restaurant_policy': 'RESTAURANT_PACK',
                     'generic_contract': 'NEUTRAL',
                     'pack_activation': 'PK',
                     'selector_resolution': 'PC4'},
 'module': {'code': 'operational_policy',
            'kind': 'shared_policy_contract',
            'owner': 'XBOS Neutral Platform',
            'source_roots': ['core/domain/operational_policy.py']},
 'schema': 'xbos.platform.pc0-n2-operational-policy-module-successor.v1',
 'source_sha256': '42825bb06cbc6a899d260004e565a3bd2762e65dafd64a77a60dd00a5b58ef9e'}
_PC0_R3_N2_EDGES = [{'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-R1-N2-R1',
  'accepted_commit': '93198dafff6f1e0809e6dba2b9e4352d8a6037a8',
  'import_name': 'core.domain.operational_policy',
  'source_module': 'orders',
  'source_path': 'core/api/orders/orders_controller.py',
  'target_module': 'operational_policy'},
 {'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-R1-N2-R1',
  'accepted_commit': '93198dafff6f1e0809e6dba2b9e4352d8a6037a8',
  'import_name': 'core.domain.operational_policy',
  'source_module': 'orders',
  'source_path': 'core/domain/orders/service.py',
  'target_module': 'operational_policy'},
 {'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-R1-N2-R1',
  'accepted_commit': '93198dafff6f1e0809e6dba2b9e4352d8a6037a8',
  'import_name': 'core.domain.operational_policy',
  'source_module': 'inventory',
  'source_path': 'core/domain/inventory/service.py',
  'target_module': 'operational_policy'},
 {'accepted_authority': 'XBOS-NEUTRAL-F-R1-B1-R1-N2-R1',
  'accepted_commit': '93198dafff6f1e0809e6dba2b9e4352d8a6037a8',
  'import_name': 'core.domain.operational_policy',
  'source_module': 'inventory',
  'source_path': 'core/domain/inventory/taxonomy_profile.py',
  'target_module': 'operational_policy'}]


def _validate_pc0_r3_policy_module(root: Path, proposed: dict[str, Any] | None = None) -> dict[str, Any]:
    if proposed is None:
        proposed = _load_json(root, "pc0_n2_operational_policy_successor.json")
    if proposed != _PC0_R3_N2_MODULE:
        _fail("PC0-R3-N2-MODULE-CONTRACT", "N2 neutral policy module declaration changed")
    module = proposed["module"]
    if module["source_roots"] != ["core/domain/operational_policy.py"] or module["code"] != "operational_policy":
        _fail("PC0-R3-N2-MODULE-ROOT", str(module))
    source = root / module["source_roots"][0]
    if not source.is_file() or _source_sha256(source) != proposed["source_sha256"]:
        _fail("PC0-R3-N2-MODULE-SOURCE-CHANGED", str(source))
    # Explicitly forbid known restaurant selection from the generic contract.
    content = source.read_text(encoding="utf-8")
    if "from restaurant." in content or "import restaurant." in content:
        _fail("PC0-R3-N2-RESTAURANT-LEAK", str(source))
    return module


def _validate_pc0_r3_policy_edges(
    root: Path, proposed: dict[str, Any] | None = None,
) -> set[tuple[str, str, str, str]]:
    if proposed is None:
        proposed = _load_json(root, "pc0_n2_operational_policy_edges.json")
    if proposed != {
        "schema": "xbos.platform.pc0-n2-exact-dependency-successor.v1",
        "authority": _PC0_R3_AUTHORITY,
        "edges": _PC0_R3_N2_EDGES,
    }:
        _fail("PC0-R3-N2-DEPENDENCY-CONTRACT", "N2 authorized import edges changed")
    return {
        (e["source_path"],e["import_name"],e["source_module"],e["target_module"])
        for e in proposed["edges"]
    }


_PC0_R3_R2_PREDECESSOR_COMMIT = "6d3c8940d99bcda77f6522200999ef0e79859792"
_PC0_R3_R2_PREDECESSOR_SHA256 = "2a0bccd2cc0301fca71badf6e5cc004e287a9f687d4cdf123f74ddf8f5a05689"
_PC0_R3_SEALED_SOURCE_PATH = "core/platform/architecture_contract.py"
_PC0_R3_SEAL_FILE = "pc0_validator_successor_seal.json"


def _validate_pc0_r3_validator_seal(
    root: Path, proposed: dict[str, Any] | None = None,
) -> dict[str, str]:
    if proposed is None:
        proposed = _load_json(root, _PC0_R3_SEAL_FILE)
    if not isinstance(proposed, dict) or set(proposed) != {
        "schema", "authority", "accepted_predecessor_commit", "files",
    } or (
        proposed["schema"] != "xbos.platform.pc0-validator-successor-seal.v1"
        or proposed["authority"] != _PC0_R3_AUTHORITY
        or proposed["accepted_predecessor_commit"] != _PC0_R3_R2_PREDECESSOR_COMMIT
    ):
        _fail("PC0-R3-SEAL-AUTHORITY", "wrong predecessor, authority or schema")
    entries = proposed["files"]
    if not isinstance(entries, list) or len(entries) != 1:
        _fail("PC0-R3-SEAL-FILE-COUNT", str(entries))
    entry = entries[0]
    if not isinstance(entry, dict) or set(entry) != {
        "path", "predecessor_sha256", "successor_sha256",
    }:
        _fail("PC0-R3-SEAL-SHAPE", str(entry))
    if entry["path"] != _PC0_R3_SEALED_SOURCE_PATH:
        _fail("PC0-R3-SEAL-UNAUTHORIZED-PATH", str(entry.get("path")))
    if entry["predecessor_sha256"] != _PC0_R3_R2_PREDECESSOR_SHA256:
        _fail("PC0-R3-SEAL-PREDECESSOR", entry["path"])
    digest = entry["successor_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        _fail("PC0-R3-SEAL-HASH-SHAPE", str(digest))
    if _source_sha256(root / entry["path"]) != digest:
        _fail("PC0-R3-SEAL-SOURCE-CHANGED", entry["path"])
    return {entry["path"]: digest}


def _pc0_r3_sealed_successor(
    root: Path, path: str, registered_predecessor: str,
) -> str | None:
    if path != _PC0_R3_SEALED_SOURCE_PATH:
        return None
    recorded = _POST_NCE_TRUSTED[path]
    predecessor_chain = [recorded["anchor"]] + [step[2] for step in recorded["commits"]]
    if registered_predecessor not in predecessor_chain:
        return None
    return _validate_pc0_r3_validator_seal(root)[path]


def _tree_fingerprint(root: Path, relative_root: str, inventory: Iterable[str], extensions: dict[str, str] | None = None) -> tuple[int, str]:
    base = root / relative_root
    expected = list(inventory)
    if len(expected) != len(set(expected)) or expected != sorted(expected):
        _fail("PC0-FROZEN-FINANCE-INVENTORY", f"{relative_root}: inventory must be unique and sorted")
    actual = sorted(
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and not _is_transient_runtime_artifact(path.relative_to(base))
    )
    extensions = extensions or {}
    allowed = set(expected) | set(extensions)
    if set(actual) != allowed:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - allowed)
        _fail(
            "PC0-FROZEN-FINANCE-INVENTORY",
            f"{relative_root}: missing={missing}, unexpected={unexpected}",
        )
    for relative, expected_hash in extensions.items():
        actual_hash = _source_sha256(base / relative)
        if actual_hash != expected_hash:
            _fail("PC0-NON-FINANCE-EXTENSION-CHANGED", f"{relative_root}/{relative}")
    files = [base / relative for relative in expected]
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return len(files), digest.hexdigest()


def _module_roots(module_map: dict[str, Any]) -> list[tuple[str, str]]:
    roots = [
        (source_root.rstrip("/"), module["code"])
        for module in module_map["modules"]
        for source_root in module["source_roots"]
    ]
    return sorted(roots, key=lambda pair: len(pair[0]), reverse=True)


def _module_for_path(path: str, roots: Iterable[tuple[str, str]]) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./")
    for source_root, module in roots:
        if normalized == source_root or normalized.startswith(source_root + "/"):
            return module
    return None


def validate_frozen_module_descendants(
    frozen_modules: dict[str, tuple[str, str]],
    module_map: dict[str, Any],
    authorities: dict[str, Any],
    reference_migrations: dict[str, Any],
) -> None:
    """Protect frozen capabilities while allowing exactly registered promotions."""
    modules = module_map.get("modules", [])
    codes = [item.get("code") for item in modules]
    if None in codes or len(codes) != len(set(codes)):
        _fail("PC0-MODULE-MAP", "duplicate/conflicting module ownership")
    actual = {item["code"]: (item.get("owner"), item.get("kind")) for item in modules}
    missing = sorted(set(frozen_modules) - set(actual))
    if missing:
        _fail("PC0-FROZEN-MODULE-MISSING", str(missing))

    governed = [item for item in reference_migrations.get("entries", []) if item.get("module_code")]
    by_module = {item["module_code"]: item for item in governed}
    if len(by_module) != len(governed):
        _fail("PC0-MODULE-PROMOTION", "duplicate governed module migration")
    authority_rows = [item for item in authorities.get("authorities", []) if item.get("module")]
    authority_by_module = {item["module"]: item for item in authority_rows}
    if len(authority_by_module) != len(authority_rows):
        _fail("PC0-MODULE-PROMOTION", "duplicate module data authority")

    required = (
        "current_authority", "target_authority", "compatibility_path",
        "retirement_owner", "retirement_milestone", "previous_module_owner",
        "previous_module_kind", "target_module_owner", "target_module_kind",
        "target_data_authority",
    )
    for code, frozen_identity in frozen_modules.items():
        current_identity = actual[code]
        if current_identity == frozen_identity:
            continue
        migration = by_module.get(code)
        authority = authority_by_module.get(code)
        if not migration or not authority or not all(isinstance(migration.get(key), str) and migration[key] for key in required):
            _fail("PC0-MODULE-PROMOTION", f"unregistered promotion={code}")
        previous = (migration["previous_module_owner"], migration["previous_module_kind"])
        target = (migration["target_module_owner"], migration["target_module_kind"])
        if previous != frozen_identity or target != current_identity:
            _fail("PC0-MODULE-PROMOTION", f"authority transition mismatch={code}")
        if authority.get("code") != migration["target_data_authority"] or authority.get("owner") != current_identity[0]:
            _fail("PC0-MODULE-PROMOTION", f"target data authority mismatch={code}")


def _path_for_import(root: Path, source_path: str, import_name: str, level: int = 0) -> str | None:
    if level:
        source_parts = Path(source_path).with_suffix("").parts[:-1]
        keep = max(0, len(source_parts) - level + 1)
        import_parts = tuple(part for part in import_name.split(".") if part)
        parts = source_parts[:keep] + import_parts
    else:
        parts = tuple(part for part in import_name.split(".") if part)
    if not parts:
        return None
    candidates = [Path(*parts).with_suffix(".py"), Path(*parts) / "__init__.py"]
    if level == 0 and parts[0] not in {"core", *ROOT_PYTHON_MODULES}:
        local = Path(source_path).parent.joinpath(*parts)
        candidates.extend([local.with_suffix(".py"), local / "__init__.py"])
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def _imports(source: str, source_path: str) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:
        _fail("PC0-PYTHON-SYNTAX", f"{source_path}:{exc.lineno}: {exc.msg}")
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                found.append((base, node.level))
            else:
                found.extend((alias.name, node.level) for alias in node.names if alias.name != "*")
    return found


def _edges_for_source(
    root: Path,
    source_path: str,
    source: str,
    roots: list[tuple[str, str]],
    admitted_unmapped_targets: set[tuple[str, str, str]] | None = None,
) -> list[ImportEdge]:
    source_module = _module_for_path(source_path, roots)
    if source_module is None:
        _fail("PC0-UNMAPPED-SOURCE", source_path)
    edges: list[ImportEdge] = []
    for import_name, level in _imports(source, source_path):
        target_path = _path_for_import(root, source_path, import_name, level)
        if target_path is None:
            continue
        target_module = _module_for_path(target_path, roots)
        if target_module is None:
            key = (source_path, import_name, target_path)
            if admitted_unmapped_targets and key in admitted_unmapped_targets:
                continue
            _fail("PC0-UNMAPPED-TARGET", f"{source_path} -> {import_name} ({target_path})")
        if source_module != target_module:
            edges.append(ImportEdge(source_path, import_name, source_module, target_module))
    return edges


def _exception_keys(exceptions: dict[str, Any]) -> dict[tuple[str, str, str, str], str]:
    if exceptions.get("matching") != "exact" or exceptions.get("wildcards_allowed") is not False:
        _fail("PC0-EXCEPTION-MODE", "only exact matching with wildcards disabled is permitted")
    result: dict[tuple[str, str, str, str], str] = {}
    ids: set[str] = set()
    required = ("source_path", "import_name", "source_module", "target_module")
    for item in exceptions.get("exceptions", []):
        exception_id = item.get("id")
        if not exception_id or exception_id in ids:
            _fail("PC0-EXCEPTION-ID", f"duplicate or blank id: {exception_id!r}")
        ids.add(exception_id)
        if any(char in str(item.get(field, "")) for field in required for char in "*?["):
            _fail("PC0-EXCEPTION-WILDCARD", exception_id)
        for field in (*required, "rationale", "retirement_owner", "retirement_milestone"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                _fail("PC0-EXCEPTION-INCOMPLETE", f"{exception_id}.{field}")
        key = tuple(item[field] for field in required)
        if key in result:
            _fail("PC0-EXCEPTION-DUPLICATE", f"{result[key]} and {exception_id}")
        result[key] = exception_id
    return result


def _evaluate_edges(
    edges: Iterable[ImportEdge], policy: dict[str, Any], exception_keys: dict[tuple[str, str, str, str], str]
) -> tuple[list[ImportEdge], set[str]]:
    allowed = policy["allowed_directions"]
    violations: list[ImportEdge] = []
    used: set[str] = set()
    for edge in edges:
        if edge.target_module in allowed.get(edge.source_module, []):
            continue
        exception_id = exception_keys.get(edge.key())
        if exception_id:
            used.add(exception_id)
        else:
            violations.append(edge)
    return violations, used


def evaluate_source_text(root: str | Path, source_path: str, source: str) -> list[dict[str, str]]:
    """Return unapproved cross-module edges for a proposed source file."""
    root_path = Path(root).resolve()
    module_map = _load_json(root_path, CONTRACT_FILES["module_map"])
    policy = _load_json(root_path, CONTRACT_FILES["dependency_policy"])
    exceptions = _load_json(root_path, CONTRACT_FILES["legacy_exceptions"])
    roots = _module_roots(module_map)
    edges = _edges_for_source(root_path, source_path, source, roots)
    violations, _ = _evaluate_edges(edges, policy, _exception_keys(exceptions))
    return [edge.__dict__ for edge in violations]


def _production_python_files(root: Path, module_map: dict[str, Any]) -> list[Path]:
    # Scan the entire production namespace, not just known roots, so a newly
    # introduced directory cannot evade the module map.
    files: set[Path] = set((root / "core").rglob("*.py"))
    for module in module_map["modules"]:
        for source_root in module["source_roots"]:
            path = root / source_root
            if path.is_file() and path.suffix == ".py":
                files.add(path)
            elif path.is_dir():
                files.update(candidate for candidate in path.rglob("*.py") if candidate.is_file())
    return sorted(files)


def _validate_modules(module_map: dict[str, Any], policy: dict[str, Any], interfaces: dict[str, Any]) -> None:
    modules = [item["code"] for item in module_map.get("modules", [])]
    if len(modules) != len(set(modules)) or not modules:
        _fail("PC0-MODULE-MAP", "module codes must be unique and nonempty")
    if set(policy.get("allowed_directions", {})) != set(modules):
        _fail("PC0-POLICY-COVERAGE", "dependency policy must declare every module exactly once")
    for source, targets in policy["allowed_directions"].items():
        if len(targets) != len(set(targets)) or not set(targets).issubset(modules):
            _fail("PC0-POLICY-TARGET", source)
    declared = [item.get("module") for item in interfaces.get("interfaces", [])]
    if len(declared) != len(set(declared)) or set(declared) != set(modules):
        _fail("PC0-INTERFACE-COVERAGE", "interface declarations must match module map")
    for item in interfaces["interfaces"]:
        public, private = item.get("public"), item.get("private")
        if not isinstance(public, list) or not isinstance(private, list):
            _fail("PC0-INTERFACE-SHAPE", item["module"])
        if set(public) & set(private):
            _fail("PC0-INTERFACE-OVERLAP", item["module"])
        if len(public) != len(set(public)) or len(private) != len(set(private)):
            _fail("PC0-INTERFACE-DUPLICATE", item["module"])


def _validate_authorities(authorities: dict[str, Any]) -> None:
    items = authorities.get("authorities", [])
    codes = [item.get("code") for item in items]
    if not items or len(codes) != len(set(codes)):
        _fail("PC0-AUTHORITY-UNIQUE", "every authority code must be unique")
    for item in items:
        owner = item.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            _fail("PC0-AUTHORITY-OWNER", str(item.get("code")))
    required = authorities.get("required_authorities", codes)
    if len(required) != len(set(required)) or set(required) != set(codes):
        _fail("PC0-AUTHORITY-COVERAGE", "required authority list does not match register")


def _validate_reference_migrations(register: dict[str, Any]) -> None:
    entries = register.get("entries", [])
    references = [entry.get("reference") for entry in entries]
    if len(references) != len(set(references)) or set(references) != set(register.get("required_references", [])):
        _fail("PC0-REFERENCE-COVERAGE", "required references must appear exactly once")
    fields = ("current_authority", "target_authority", "compatibility_path", "retirement_owner", "retirement_milestone")
    for entry in entries:
        for field in fields:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                _fail("PC0-REFERENCE-INCOMPLETE", f"{entry.get('reference')}.{field}")


def _validate_composition(
    root: Path, composition: dict[str, Any], successor: dict[str, Any] | None = None
) -> None:
    if successor is None:
        successor = _load_h1b_successor(root)
    else:
        successor = _validate_h1b_successor_contract(root, successor)
    if composition.get("fingerprint_mode") != "sha256_git_canonical_lf":
        _fail("PC0-COMPOSITION-FINGERPRINT-MODE", str(composition.get("fingerprint_mode")))
    override = successor.get("composition_override") if successor else None
    nce_override = (
        successor.get("nce_additive_successor", {}).get("kernel_router_override")
        if successor else None
    )
    pc8_replacements = _pc8_composition_replacements(root)
    for relative, expected in composition.get("files", {}).items():
        actual = _source_sha256(root / relative)
        if actual == expected:
            continue
        if (
            override
            and relative == override["path"]
            and expected == override["historical_sha256"]
            and actual == override["successor_sha256"]
        ):
            continue
        if (
            nce_override
            and relative == nce_override["path"]
            and expected == nce_override["historical_sha256"]
            and actual == nce_override["successor_sha256"]
        ):
            continue
        if (
            relative == "core/api/kernel_router.py"
            and nce_override
            and expected == nce_override["historical_sha256"]
            and _validate_vn0_browser_successor(root) is not None
            and actual == _VN0_C2_KERNEL_SHA256
        ):
            continue
        pc8 = pc8_replacements.get(relative)
        if pc8 and pc8 == (expected, actual):
            continue
        if _post_nce_resolved_hash(root, relative, expected) == actual:
            continue
        _fail("PC0-COMPOSITION-CHANGED", f"{relative}: {actual} != {expected}")
    for relative, markers in composition.get("markers", {}).items():
        source = (root / relative).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                _fail("PC0-COMPOSITION-MARKER", f"{relative}: {marker}")
    facts = composition.get("facts", {})
    if facts.get("canonical_entrypoint") != "main:app" or facts.get("compatibility_entrypoint") != "app:app":
        _fail("PC0-ENTRYPOINT", "canonical or compatibility entrypoint changed")
    if facts.get("production_dependency_authority") != "requirements-prod.txt":
        _fail("PC0-DEPENDENCY-AUTHORITY", "requirements-prod.txt must remain canonical")


def _migration_revisions(root: Path) -> tuple[list[str], list[str]]:
    revisions: dict[str, str | None] = {}
    for path in sorted((root / "alembic_neutral/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        if "revision" in values:
            if values["revision"] in revisions:
                _fail("PC0-MIGRATION-LINEAGE", f"duplicate revision {values['revision']}")
            revisions[values["revision"]] = values.get("down_revision")
    parents = {parent for parent in revisions.values() if isinstance(parent, str)}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        return heads, []
    lineage: list[str] = []
    current: str | None = heads[0]
    while current:
        if current in lineage or current not in revisions:
            _fail("PC0-MIGRATION-LINEAGE", f"broken or cyclic lineage at {current}")
        lineage.append(current)
        current = revisions[current]
    return heads, list(reversed(lineage))


def _validate_migration_lineage(
    heads: list[str], lineage: list[str], finance: dict[str, Any], accepted_heads: Iterable[str] = ()
) -> None:
    """Protect the immutable Finance prefix while permitting one linear descendant tail."""
    if isinstance(accepted_heads, str):
        accepted_heads = (accepted_heads,)
    frozen = finance.get("lineage", [])
    canonical = finance.get("canonical_head")
    if not frozen or frozen[-1] != canonical:
        _fail("PC0-MIGRATION-LINEAGE", "frozen Finance lineage or canonical head declaration is invalid")
    if len(heads) != 1:
        _fail("PC0-MIGRATION-HEAD", f"heads={heads}, lineage={lineage}")
    if len(lineage) < len(frozen) or lineage[:len(frozen)] != frozen:
        _fail("PC0-MIGRATION-HEAD", f"frozen_prefix={frozen}, heads={heads}, lineage={lineage}")
    declared = [head for head in accepted_heads if head]
    declared_end = len(frozen) + len(declared)
    if len(lineage) < declared_end or lineage[len(frozen):declared_end] != declared:
        _fail("PC0-MIGRATION-HEAD", f"declared_descendants={declared}, heads={heads}, lineage={lineage}")
    if heads != [lineage[-1]]:
        _fail("PC0-MIGRATION-HEAD", f"heads={heads}, lineage={lineage}")


def _validate_finance(
    root: Path,
    finance: dict[str, Any],
    inventory: dict[str, Any],
    accepted_heads: Iterable[str] = (),
    successor: dict[str, Any] | None = None,
) -> None:
    if successor is None:
        successor = _load_h1b_successor(root)
    else:
        successor = _validate_h1b_successor_contract(root, successor)
    if isinstance(accepted_heads, str):
        accepted_heads = (accepted_heads,)
    if finance.get("fingerprint_mode") != "sha256_git_canonical_lf":
        _fail("PC0-FINANCE-FINGERPRINT-MODE", str(finance.get("fingerprint_mode")))
    if inventory.get("freeze_commit") != finance.get("freeze_commit"):
        _fail("PC0-FROZEN-FINANCE-INVENTORY", "inventory checkpoint does not match baseline")
    inventory_trees = {tree.get("root"): tree for tree in inventory.get("trees", [])}
    if set(inventory_trees) != {tree.get("root") for tree in finance.get("trees", [])}:
        _fail("PC0-FROZEN-FINANCE-INVENTORY", "protected tree coverage does not match baseline")
    extensions_by_root: dict[str, dict[str, str]] = {}
    for item in inventory.get("authorized_non_finance_extensions", []):
        owner = item.get("owner")
        valid_owner = isinstance(owner, str) and (
            (owner.startswith("PC") and owner[2:].isdigit() and int(owner[2:]) >= 1)
            or (owner.startswith("SO") and owner[2:].isdigit() and 1 <= int(owner[2:]) <= 10)
            or (owner.startswith("PK") and (owner == "PK" or owner[2:].isdigit()))
            or owner == "PA"
        )
        if not valid_owner or not all(isinstance(item.get(key), str) and item[key] for key in ("root","path","sha256")):
            _fail("PC0-NON-FINANCE-EXTENSION", str(item))
        extensions_by_root.setdefault(item["root"], {})[item["path"]] = item["sha256"]
    if successor:
        for item in successor["non_finance_extensions"]:
            extensions_by_root.setdefault(item["root"], {})[item["path"]] = item["sha256"]
    # Frozen pre-H1B fixtures must still validate their original Finance
    # prefix without requiring future extension declarations.
    if successor:
        r3_extensions = _validate_pc0_r3_migration_extensions(root)
        existing = extensions_by_root.setdefault("alembic_neutral", {})
        for relative, digest in r3_extensions.items():
            if relative in existing and existing[relative] != digest:
                _fail("PC0-R3-MIGRATION-EXTENSION-CONFLICT", relative)
            existing[relative] = digest
    for tree in finance.get("trees", []):
        declared = inventory_trees[tree["root"]]
        files = declared.get("files", [])
        suffixes = set(declared.get("protected_suffixes", []))
        if not suffixes or any(Path(relative).suffix not in suffixes for relative in files):
            _fail("PC0-FROZEN-FINANCE-INVENTORY", f"{tree['root']}: invalid protected suffix declaration")
        count, actual = _tree_fingerprint(root, tree["root"], files, extensions_by_root.get(tree["root"]))
        if count != tree["file_count"] or actual != tree["sha256"]:
            _fail("PC0-FROZEN-FINANCE-CHANGED", f"{tree['root']}: count={count}, sha256={actual}")
    heads, lineage = _migration_revisions(root)
    _validate_migration_lineage(heads, lineage, finance, accepted_heads)
    if successor:
        migration = successor["migration"]
        expected_tail = [migration["revision"], *_PC0_R3_MIGRATION_REVISIONS]
        if (
            heads != [_PC0_R3_MIGRATION_REVISIONS[-1]]
            or lineage[-len(expected_tail):] != expected_tail
            or lineage[-len(expected_tail)-1] != migration["parent"]
        ):
            _fail("PC0-H1B-MIGRATION-SUCCESSOR", f"heads={heads}, tail={lineage[-len(expected_tail)-1:]}")
    boundaries = finance.get("boundaries", {})
    if boundaries.get("migration") != "NONE" or boundaries.get("schema_neutral") is not True:
        _fail("PC0-SCHEMA-NEUTRAL", "PC0 may not carry a migration")


def _validate_kernel(kernel: dict[str, Any]) -> None:
    if kernel.get("scope") != [f"PC0.{number}" for number in range(1, 9)]:
        _fail("PC0-SCOPE", "PC0.1-PC0.8 must be complete")
    if kernel.get("platform_core_wbs_obligations") != 80:
        _fail("PC0-WBS", "the authoritative Platform Core obligation count is 80")
    exclusions = set(kernel.get("exclusions", []))
    required = {"alembic_migration", "database_write", "runtime_behavior_change", "pc1_pc6_implementation"}
    if not required.issubset(exclusions):
        _fail("PC0-EXCLUSIONS", f"missing {sorted(required - exclusions)}")


def validate_pc0(root: str | Path, validate_release: bool = True) -> dict[str, Any]:
    """Validate the complete static PC0 contract and return deterministic counts."""
    root_path = Path(root).resolve()
    contracts = {key: _load_json(root_path, name) for key, name in CONTRACT_FILES.items()}
    successor = _load_h1b_successor(root_path)
    _validate_modules(contracts["module_map"], contracts["dependency_policy"], contracts["interfaces"])
    if set(contracts["composition"].get("files", {})) != set(contracts["module_map"].get("composition_files", [])):
        _fail("PC0-COMPOSITION-COVERAGE", "composition baseline must exactly match the module-map inventory")
    _validate_authorities(contracts["authorities"])
    _validate_reference_migrations(contracts["reference_migrations"])
    _validate_composition(root_path, contracts["composition"], successor)
    descendant_heads = [
        contracts["pc1"].get("accepted_head"), contracts["pc2"].get("accepted_head"),
        contracts["pc3"].get("accepted_head"), contracts["pc4"].get("accepted_head"),
        contracts["pc5"].get("accepted_head"),
    ]
    # Shared Operations descendants are a bounded constitutional sequence SO1-SO10.
    # Discover them prospectively so each legitimate next milestone does not require
    # another hard-coded architecture validator edit merely to extend the lineage.
    for number in range(1, 11):
        contract = root_path / f"contracts/shared_operations/v1/so{number}_authority.json"
        if contract.is_file():
            descendant_heads.append(json.loads(contract.read_text(encoding="utf-8")).get("accepted_head"))
    aggregate_contract = root_path / "contracts/shared_operations/v1/so_aggregate_conformance_freeze.json"
    if aggregate_contract.is_file():
        descendant_heads.append(json.loads(aggregate_contract.read_text(encoding="utf-8")).get("accepted_head"))
    # Pack Platform descendants are likewise prospective governed descendants.
    for contract in sorted((root_path / "contracts/packs/v1").glob("pk*_authority.json")) if (root_path / "contracts/packs/v1").is_dir() else []:
        descendant_heads.append(json.loads(contract.read_text(encoding="utf-8")).get("accepted_head"))
    _validate_finance(
        root_path,
        contracts["finance"],
        contracts["finance_inventory"],
        descendant_heads,
        successor,
    )
    _validate_kernel(contracts["kernel"])

    n2_module = _validate_pc0_r3_policy_module(root_path)
    roots = sorted(
        [*_module_roots(contracts["module_map"]), (n2_module["source_roots"][0], n2_module["code"])],
        key=lambda item: len(item[0]), reverse=True,
    )
    n2_policy_edges = _validate_pc0_r3_policy_edges(root_path)
    successor_edges: set[tuple[str, str, str, str]] = set(n2_policy_edges)
    if successor:
        nce = successor["nce_additive_successor"]
        overlay = nce["module_overlay"]
        roots = sorted(
            [*roots, (overlay["source_root"].rstrip("/"), overlay["module_code"])],
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        successor_edges |= {
            (
                item["source_path"], item["import_name"],
                item["source_module"], item["target_module"],
            )
            for item in nce["authorized_dependency_edges"]
        }
    exception_keys = _exception_keys(contracts["legacy_exceptions"])
    edges: list[ImportEdge] = []
    admitted_unmapped_targets = {
        ("startup.py", "restaurant.customer_channel.router", "restaurant/customer_channel/router.py")
    } if successor else set()
    files = _production_python_files(root_path, contracts["module_map"])
    for path in files:
        relative = path.relative_to(root_path).as_posix()
        edges.extend(
            _edges_for_source(
                root_path,
                relative,
                path.read_text(encoding="utf-8"),
                roots,
                admitted_unmapped_targets,
            )
        )
    violations, used = _evaluate_edges(edges, contracts["dependency_policy"], exception_keys)
    if successor_edges:
        present_successor_edges = {edge.key() for edge in edges if edge.key() in successor_edges}
        if present_successor_edges != successor_edges:
            _fail(
                "PC0-NCE-DEPENDENCY-EDGE-MISSING",
                str(sorted(successor_edges - present_successor_edges)),
            )
        violations = [edge for edge in violations if edge.key() not in successor_edges]
    if violations:
        edge = violations[0]
        _fail("PC0-DEPENDENCY-DENIED", " -> ".join(edge.key()))
    expected_ids = set(exception_keys.values())
    if used != expected_ids:
        _fail("PC0-EXCEPTION-BASELINE-DRIFT", f"unused={sorted(expected_ids-used)}, unknown={sorted(used-expected_ids)}")

    result = {
        "status": "PASS",
        "module_count": len(contracts["module_map"]["modules"]),
        "authority_count": len(contracts["authorities"]["authorities"]),
        "reference_migration_count": len(contracts["reference_migrations"]["entries"]),
        "legacy_exception_count": len(exception_keys),
        "production_python_file_count": len(files),
        "cross_module_edge_count": len(edges),
        "successor_dependency_edge_count": len(successor_edges),
        "nce_source_file_count": len(_NCE_SOURCE_HASHES) if successor else 0,
        "canonical_migration_head": contracts["finance"]["canonical_head"],
    }
    if validate_release:
        manifest = _load_json(root_path, "pc0_release_manifest.json")
        replacements = {
            item["path"]: item for item in successor.get("pc0_release_replacements", [])
        } if successor else {}
        used_replacements: set[str] = set()
        for item in manifest.get("artifacts", []):
            path = root_path / item["path"]
            if not path.is_file():
                _fail("PC0-RELEASE-MANIFEST", item["path"])
            actual = _sha256_file(path)
            if actual == item["sha256"]:
                continue
            replacement = replacements.get(item["path"])
            if not replacement or replacement["historical_sha256"] != item["sha256"]:
                _fail("PC0-RELEASE-MANIFEST", item["path"])
            if replacement["successor_sha256"] != actual:
                registered = _post_nce_resolved_hash(root_path, item["path"], replacement["successor_sha256"])
                if registered != actual and item["path"] == _PC0_R3_SEALED_SOURCE_PATH:
                    registered = _pc0_r3_sealed_successor(root_path, item["path"], replacement["successor_sha256"])
                if registered != actual:
                    _fail("PC0-RELEASE-MANIFEST", item["path"])
            used_replacements.add(item["path"])
        if used_replacements != set(replacements):
            _fail("PC0-H1B-RELEASE-REPLACEMENTS", f"unused={sorted(set(replacements)-used_replacements)}")
        result["release_artifact_count"] = len(manifest.get("artifacts", []))
    return result
