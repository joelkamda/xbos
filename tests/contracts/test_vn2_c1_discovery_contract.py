"""VN2 C1: frozen contract-only discovery evidence. No database or HTTP calls."""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/platform/v1/vn2_pack_template_discovery_v1.json"
PK_SCHEMA_SQL = (ROOT / "alembic_neutral/sql/pk0123_pack_manifest_lifecycle_up.sql").read_text(encoding="utf-8")
PK456_SCHEMA_SQL = (ROOT / "alembic_neutral/sql/pk456_pack_conformance_templates_up.sql").read_text(encoding="utf-8")
PACK_REPOSITORY = (ROOT / "pack_platform/sql_repository.py").read_text(encoding="utf-8")
TEMPLATE_REPOSITORY = (ROOT / "pack_platform/pk456_sql_repository.py").read_text(encoding="utf-8")
KERNEL_ROUTER = (ROOT / "core/api/kernel_router.py").read_text(encoding="utf-8")
BROWSER_ROUTER = (ROOT / "core/auth/browser_session_router.py").read_text(encoding="utf-8")


def accepted_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def validate_subset_schema(schema: dict, payload: object, path: str = "$") -> None:
    """Test-local evaluator for the closed, deliberately small JSON-schema subset."""
    if "oneOf" in schema:
        valid = 0
        for candidate in schema["oneOf"]:
            try:
                validate_subset_schema(candidate, payload, path)
            except AssertionError:
                continue
            valid += 1
        assert valid == 1, f"{path}: expected exactly one matching shape, saw {valid}"
        return
    if "const" in schema:
        assert payload == schema["const"], f"{path}: invalid constant"
        return
    typ = schema.get("type")
    if typ == "object":
        assert isinstance(payload, dict), f"{path}: expected object"
        required = set(schema["required"])
        assert required.issubset(payload), f"{path}: missing {required - set(payload)}"
        if schema.get("additionalProperties") is False:
            assert set(payload) <= set(schema["properties"]), f"{path}: forbidden keys {set(payload) - set(schema['properties'])}"
        for key, value in payload.items():
            validate_subset_schema(schema["properties"][key], value, f"{path}.{key}")
    elif typ == "array":
        assert isinstance(payload, list), f"{path}: expected array"
        for i, value in enumerate(payload):
            validate_subset_schema(schema["items"], value, f"{path}[{i}]")
    elif typ == "integer":
        assert isinstance(payload, int) and not isinstance(payload, bool), f"{path}: expected integer"
        assert payload >= schema.get("minimum", 0), f"{path}: below minimum"
    elif typ == "string":
        assert isinstance(payload, str), f"{path}: expected string"
        assert len(payload) >= schema.get("minLength", 0), f"{path}: empty"
        if "enum" in schema:
            assert payload in schema["enum"], f"{path}: unknown enum"
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], payload), f"{path}: invalid digest"


def paths_of_leaves(schema: dict, prefix: str = "") -> set[str]:
    """Fields exposed in all branches, including optional applied-only leaves."""
    if "oneOf" in schema:
        return set().union(*(paths_of_leaves(part, prefix) for part in schema["oneOf"]))
    if "const" in schema or schema.get("type") not in {"array", "object"}:
        return {prefix}
    if schema["type"] == "array":
        return paths_of_leaves(schema["items"], prefix + "/*")
    return set().union(*(paths_of_leaves(sub, prefix + "/" + name)
                         for name, sub in schema["properties"].items()))


SAMPLE = {
    "schema": "xbos.platform.pack-template-discovery.v1", "tenant_ref": 19,
    "packs": [
        {"pack_code": "neutral.capability", "owner_code": "platform",
         "pack_kind": "capability",
         "versions": [{"version": "1.0.0", "manifest_sha256": "a" * 64,
                       "retention_required": True}],
         "tenant_state": {"status": "ABSENT"}},
        {"pack_code": "neutral.connector", "owner_code": "platform",
         "pack_kind": "payment_connector",
         "versions": [{"version": "2.0.0", "manifest_sha256": "b" * 64,
                       "retention_required": True}],
         "tenant_state": {"status": "INSTALLED", "version": "2.0.0",
                          "row_version": 2}},
    ],
    "templates": [
        {"template_code": "neutral.template", "owner_code": "platform",
         "versions": [{"version": "1.0.0", "template_sha256": "c" * 64,
                       "industry_semantic_ref": "semantic:neutral",
                       "operating_model_semantic_ref": "model:neutral",
                       "requirements": [
                           {"pack_code": "neutral.capability", "version": "1.0.0",
                            "kind": "REQUIRED"}]}],
         "tenant_state": {"status": "APPLIED", "version": "1.0.0",
                          "row_version": 1, "selected_optional_packs": []}},
    ],
}


class VN2C1DiscoveryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = accepted_contract()

    def test_frozen_name_route_method_no_body(self):
        self.assertEqual(self.c["contract_name"], "xbos.platform.pack-template-discovery.v1")
        self.assertEqual(self.c["design_authority"], "XBOS-NEUTRAL-VN2-R1-C1")
        self.assertEqual(self.c["method"], "GET")
        self.assertEqual(self.c["canonical_path"], "/api/kernel/platform/v1/pack-template-discovery")
        self.assertEqual(self.c["request"]["body"], "FORBIDDEN")
        self.assertEqual(self.c["request"]["query_parameters"], "NONE")

    def test_existing_browser_identity_is_the_only_tenant_source(self):
        a = self.c["authentication"]
        self.assertEqual(a["session_profile"], "browser-session.v1")
        self.assertIn("browser_access", a["trusted_context_source"])
        self.assertIn("validate", a["validation"].lower())
        self.assertIn("tenant_id", a["tenant_scope"])
        self.assertIn("session", a["tenant_scope"])
        self.assertEqual(self.c["request"]["tenant_header_override"], "FORBIDDEN")
        self.assertIn("tenant_id", self.c["projection"]["field_provenance"][0]["source"])
        self.assertIn('@auth_router.get("/me"', (ROOT / "core/auth/auth_controller.py").read_text(encoding="utf-8"))
        self.assertIn("validate_browser_access", (ROOT / "core/auth/auth_controller.py").read_text())
        self.assertIn("browser-session/v1", BROWSER_ROUTER)

    def test_existing_middleware_fallback_is_rejected_as_authority(self):
        assert "X-Tenant-Code" in (ROOT / "core/middleware/tenant_middleware.py").read_text(encoding="utf-8")
        assert "DEV_TENANT_CODE" in (ROOT / "core/middleware/tenant_middleware.py").read_text(encoding="utf-8")
        assert "X-Branch-Code" in (ROOT / "core/middleware/branch_middleware.py").read_text(encoding="utf-8")
        self.assertIn("MUST NOT", self.c["authentication"]["middleware_hazard"])
        self.assertIn("browser identity", self.c["authentication"]["middleware_hazard"])

    def test_top_level_exact_and_tenant_server_derived(self):
        schema = self.c["response_schema"]
        self.assertEqual(set(schema["required"]), {"schema", "tenant_ref", "packs", "templates"})
        self.assertEqual(set(schema["properties"]), {"schema", "tenant_ref", "packs", "templates"})
        self.assertFalse(schema["additionalProperties"])
        validate_subset_schema(schema, SAMPLE)
        with self.assertRaises(AssertionError):
            validate_subset_schema(schema, {**SAMPLE, "tenant_id": 28})

    def test_empty_catalog_is_not_default_pack(self):
        empty = {"schema": SAMPLE["schema"], "tenant_ref": 19, "packs": [], "templates": []}
        validate_subset_schema(self.c["response_schema"], empty)
        self.assertEqual(self.c["ordering"]["empty_lists"], "[]; no default item, no automatic selection")

    def test_pack_state_absence_is_explicit_and_not_entitlement(self):
        schema = self.c["response_schema"]
        bad = copy.deepcopy(SAMPLE)
        bad["packs"][0]["tenant_state"] = {"status": "ABSENT", "version": "1.0.0"}
        with self.assertRaises(AssertionError):
            validate_subset_schema(schema, bad)
        self.assertIn("neither eligible nor ineligible", self.c["projection"]["tenant_pack_absence"]["meaning"])

    def test_pack_tenant_state_requires_version_and_row_version_when_present(self):
        bad = copy.deepcopy(SAMPLE)
        bad["packs"][1]["tenant_state"].pop("row_version")
        with self.assertRaises(AssertionError):
            validate_subset_schema(self.c["response_schema"], bad)

    def test_template_state_absence_or_applied_only(self):
        absent = copy.deepcopy(SAMPLE)
        absent["templates"][0]["tenant_state"] = {"status": "ABSENT"}
        validate_subset_schema(self.c["response_schema"], absent)
        for invalid in ("ACTIVE", "ELIGIBLE", "SELECTED"):
            bad = copy.deepcopy(SAMPLE)
            bad["templates"][0]["tenant_state"] = {"status": invalid}
            with self.assertRaises(AssertionError):
                validate_subset_schema(self.c["response_schema"], bad)

    def test_registry_presence_does_not_create_entitlement(self):
        all_fields = paths_of_leaves(self.c["response_schema"])
        for forbidden in ("eligible", "entitled", "available_to_tenant", "is_selected",
                          "is_active_default"):
            self.assertNotIn(forbidden, {p.rsplit("/", 1)[-1] for p in all_fields})
            self.assertIn(forbidden, self.c["forbidden_response_fields"])
        self.assertIn("NOT", self.c["projection"]["packs"])

    def test_pack_and_template_fields_all_have_provenance(self):
        fields = paths_of_leaves(self.c["response_schema"]) - {"/schema"}
        mapped = [item["path"] for item in self.c["projection"]["field_provenance"]]
        self.assertEqual(set(mapped), fields)
        self.assertEqual(len(mapped), len(set(mapped)))
        for item in self.c["projection"]["field_provenance"]:
            self.assertTrue(item["source"] and item["authority"] and item["meaning"])

    def test_provenance_references_existing_schema_columns(self):
        sql = PK_SCHEMA_SQL + "\n" + PK456_SCHEMA_SQL
        for item in self.c["projection"]["field_provenance"]:
            source = item["source"]
            if source.startswith("validated browser"):
                continue
            for token in re.findall(r"pk_[a-z_]+(?:\\.[a-z_]+)?", source):
                table, _, column = token.partition(".")
                self.assertIn("CREATE TABLE public." + table + "(", sql, item["path"])
                if column:
                    self.assertIn(column, sql, item["path"])
        for table in self.c["read_boundary"]["allowed_sources"]:
            self.assertIn("CREATE TABLE public." + table + "(", sql)

    def test_no_raw_manifests_credentials_xa_or_internal_configuration(self):
        exposed = {p.rsplit("/", 1)[-1] for p in paths_of_leaves(self.c["response_schema"])}
        self.assertFalse(exposed & {
            "manifest_json", "template_json", "access_token", "secret_reference_keys",
            "configuration_defaults", "xa", "xa_json", "terminology", "raw_payload",
            "selected_pack_id", "permissions", "private_key"
        })
        bad = copy.deepcopy(SAMPLE)
        bad["packs"][0]["versions"][0]["manifest_json"] = {"secret": "unsafe"}
        with self.assertRaises(AssertionError):
            validate_subset_schema(self.c["response_schema"], bad)

    def test_semantic_references_are_stored_fields_not_defaults(self):
        sql = PK456_SCHEMA_SQL
        self.assertIn("industry_semantic_ref", sql)
        self.assertIn("operating_model_semantic_ref", sql)
        self.assertEqual(self.c["neutrality"]["defaults"], "NONE")
        self.assertEqual(self.c["neutrality"]["hardcoded_industry"], "NONE")

    def test_safe_explicit_deterministic_ordering(self):
        ordering = self.c["ordering"]
        self.assertEqual(ordering["packs"], "pack_code ASC")
        self.assertEqual(ordering["templates"], "template_code ASC")
        self.assertIn("pack_version ASC", ordering["pack_versions"])
        self.assertIn("template_version ASC", ordering["template_versions"])
        self.assertIn("ordinal", ordering["collation"])
        self.assertIn("requirement_kind ASC", ordering["template_requirements"])

    def test_error_codes_allowlisted_without_database_error_leakage(self):
        errors = self.c["errors"]
        cases = errors["cases"]
        self.assertEqual({x["code"] for x in cases},
                         {"UNAUTHENTICATED", "TRUST_CONTEXT_UNAVAILABLE",
                          "TENANT_CONTEXT_UNAVAILABLE", "DISCOVERY_UNAVAILABLE"})
        self.assertEqual({x["code"]: x["http_status"] for x in cases},
                         {"UNAUTHENTICATED": 401, "TRUST_CONTEXT_UNAVAILABLE": 403,
                          "TENANT_CONTEXT_UNAVAILABLE": 403, "DISCOVERY_UNAVAILABLE": 503})
        for case in cases:
            validate_subset_schema(errors["envelope"], {"error": {"code": case["code"]}})
        with self.assertRaises(AssertionError):
            validate_subset_schema(errors["envelope"],
                                   {"error": {"code": "DISCOVERY_UNAVAILABLE", "sql": "bad"}})

    def test_no_callsite_or_runtime_write_granted(self):
        self.assertEqual(self.c["read_boundary"]["future_route_implementation"],
                         "NOT_AUTHORIZED_UNDER_C1")
        self.assertIn("no initialization", self.c["read_boundary"]["transaction"])
        for command in ("INSERT", "UPDATE", "DELETE", "FOR UPDATE", "apply_template",
                        "upgrade_template", "activate"):
            self.assertIn(command, self.c["forbidden_runtime_actions"])
        self.assertNotIn("pack-template-discovery", KERNEL_ROUTER)
        self.assertNotIn("include_router(platform", KERNEL_ROUTER)

    def test_cache_is_never_a_source_of_authority(self):
        self.assertEqual(self.c["cache"]["response"], "Cache-Control: private, no-store")
        self.assertEqual(self.c["cache"]["stale_authority"], "forbidden")
        self.assertIn("never", self.c["cache"]["client_local_selection"])

    def test_no_hardcoded_industry_or_tenant_in_schema(self):
        schema = json.dumps(self.c["response_schema"]).lower()
        for forbidden in ("wnd", "logpom", "restaurant", "tenant_2", "cm001",
                          "dining_area", "table_number", "merchant"):
            self.assertNotIn(forbidden, schema)

    def test_malformed_state_or_unknown_response_field_rejected(self):
        invalid = copy.deepcopy(SAMPLE)
        invalid["packs"][1]["tenant_state"]["status"] = "ELIGIBLE"
        with self.assertRaises(AssertionError):
            validate_subset_schema(self.c["response_schema"], invalid)
        invalid = copy.deepcopy(SAMPLE)
        invalid["templates"][0]["versions"][0]["requirements"][0]["kind"] = "ACTIVATED"
        with self.assertRaises(AssertionError):
            validate_subset_schema(self.c["response_schema"], invalid)

    def test_existing_pack_and_template_internal_owners_are_preserved(self):
        self.assertIn("def state(self,tenant_id,pack_code):", PACK_REPOSITORY)
        self.assertIn("def template_version(self, code: str, version: str):", TEMPLATE_REPOSITORY)
        self.assertIn("def tenant_template(self, tenant_id: int, template_code: str):",
                      TEMPLATE_REPOSITORY)
        self.assertIn("pk_tenant_pack_installations", PK_SCHEMA_SQL)
        self.assertIn("pk_tenant_template_bindings", PK456_SCHEMA_SQL)
        self.assertEqual(len(self.c["read_boundary"]["allowed_sources"]), 7)


if __name__ == "__main__":
    unittest.main()
