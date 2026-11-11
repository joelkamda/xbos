"""PK D2 SOURCE-only preview tests against accepted D0 MerchantBlueprint specimens.

Everything here is simulated. No hosted PC1/PA/PK/PC4/PC5/PSP authority,
real merchant activation or database mutation may be inferred from PASS.
"""
from __future__ import annotations
import copy
import hashlib
import json
import pathlib
import unittest
from pack_platform.d2_activation_plan_compiler import (
    ActivationPlanCompilationError,
    compile_activation_plan,
)
from pack_platform.pk456_service import _REQUIRED_CERTIFICATION_CHECKS

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "xcomp_pk_d2_accepted_blueprints.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
TIME = "2026-11-09T12:00:00+00:00"

def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()

def fixture(profile="restaurant", *, issued_b=False):
    bp = copy.deepcopy(RAW["specimens"][profile])
    if profile == "payments_only" and issued_b:
        # Hypothetical fixture only, not an issued B merchant.
        bp["tenant"].update(numeric_id=920002,
                            merchant_public_uuid="00000000-0000-4000-8000-000000009202")
    return bp

def facts(bp):
    tid = bp["tenant"]["numeric_id"]
    packs = []
    for p in bp["packs"]:
        packs.append({
            "code": p["code"], "version": p["version"],
            "manifest_sha256": sha("synthetic.manifest:" + p["code"]),
            "certification_evidence_sha256": sha("synthetic.certification:" + p["code"]),
            "certification": "PASS", "status": "ACTIVE",
            "passed_checks": sorted(_REQUIRED_CERTIFICATION_CHECKS),
            "eligible_countries": ["CM"],
        })
    template = bp["template"]
    requirements = [{"code": p["code"], "version": p["version"]} for p in
                    sorted(bp["packs"], key=lambda row: row["code"])]
    source = {p: {"producer": p.upper(), "proof_grade": "SYNTHETIC_ONLY",
                   "source_digest": sha("SYNTHETIC:" + p),
                   "as_of": "2026-11-09T11:00:00+00:00",
                   "expires_at": "2026-11-09T13:00:00+00:00"}
              for p in ("pc1", "pa", "pk", "pc4", "pc5", "policy")}
    source["pc1"].update(tenant_id=tid, merchant_public_uuid=bp["tenant"]["merchant_public_uuid"],
                         profile=bp["merchant_profile"], branch_id=5, issued=True)
    source["pa"].update(tenant_id=tid, owner_consent="APPROVED",
                        owner_proof_ref="SYNTHETIC_PA_ONLY",
                        lifecycle="ONBOARDING_READY", subscription="ACTIVE")
    source["pk"].update(tenant_id=tid, packs=packs,
                        template={"code": template["code"], "version": template["version"],
                                  "sha256": sha("SYNTHETIC_TEMPLATE:" + template["code"]),
                                  "status": "ACTIVE", "required_packs": requirements})
    source["pc4"].update(tenant_id=tid, subscription_entitled=True,
                         finance_kernel_enabled=True, country="CM",
                         effective_modules=bp["modules"]["required"], xafchat_entitled=False)
    source["pc5"].update(tenant_id=tid, branch_id=5, active=True, revoked=False,
                         assurance="A2", permissions=["pack.activation_plan.preview"])
    source["policy"].update(country="CM", tax_eligible=True, jurisdiction_eligible=True,
                            payment_connector_eligible=True, provider_status="ADMITTED",
                            provider_countries=["CM"], xafchat_connector_eligible=False)
    return source

def compile_(bp, source, **kwargs):
    return compile_activation_plan(bp, source, evaluated_at=TIME, **kwargs)

class PKD2PreviewTests(unittest.TestCase):
    def setUp(self):
        self.a = fixture()
        self.f = facts(self.a)

    def blocked(self, code, bp=None, source=None, **kwargs):
        with self.assertRaises(ActivationPlanCompilationError) as raised:
            compile_(bp if bp is not None else self.a,
                     source if source is not None else self.f, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_source_provenance_pinned_accepted(self):
        self.assertEqual(RAW["schema"], "xcomp.MerchantBlueprint.v1")
        self.assertEqual(RAW["source_d0_contract_sha256"],
                         "555cda0afeaf515d3163088c43dedee21c82a257cba61f54d27adf877b15734a")
    def test_wnd_hypothetical_source_only_success(self):
        v = compile_(self.a, self.f)
        self.assertFalse(v["activation_permitted"])
        self.assertEqual(v["grade"], "NONOPERATIVE_LOCAL_SYNTHETIC_ONLY")
        self.assertEqual(v["mandatory_packs"][0]["code"], "industry.restaurant")
        self.assertEqual(v["template"]["code"], "restaurant.counter_service")
        self.assertEqual(v["optional_packs"], [])
        self.assertEqual(len(v["plan_sha256"]), 64)
        self.assertIn("HOLD_FOR_SEPARATELY_AUTHORIZED_D2_RELEASE", v["steps"])
    def test_rebuild_identical_digest(self):
        x, y = compile_(self.a, self.f), compile_(copy.deepcopy(self.a), copy.deepcopy(self.f))
        self.assertEqual(x, y)
    def test_json_key_reordering_stable(self):
        a = json.loads(json.dumps(self.a, sort_keys=True))
        f = json.loads(json.dumps(self.f, sort_keys=True))
        self.assertEqual(compile_(a, f)["plan_sha256"], compile_(self.a, self.f)["plan_sha256"])
    def test_inputs_not_mutated(self):
        before = (copy.deepcopy(self.a), copy.deepcopy(self.f))
        compile_(self.a, self.f)
        self.assertEqual((self.a, self.f), before)
    def test_blueprint_revision_digest_changes_plan(self):
        old = compile_(self.a, self.f)
        b = copy.deepcopy(self.a);b["revision"] = 2
        self.assertNotEqual(old["plan_sha256"], compile_(b, self.f)["plan_sha256"])
    def test_b_unissued_cannot_compile(self):
        b = fixture("payments_only")
        self.blocked("PK_D2_TENANT_UNISSUED", b, facts(b))
    def test_b_issued_only_hypothetical_graph(self):
        b = fixture("payments_only", issued_b=True)
        v = compile_(b, facts(b))
        self.assertEqual({p["code"] for p in v["mandatory_packs"]},
                         {"neutral.foundation", "neutral.payments"})
        self.assertEqual(v["template"]["code"], "neutral.payments_only")
        self.assertFalse(v["activation_permitted"])
    def test_b_wnd_shifts_denied(self):
        b = fixture("payments_only", issued_b=True)
        b["business_policy"]["tenant_overrides"]["shifts"]=["08:00-18:00"]
        self.blocked("PK_D2_WND_POLICY_INHERITANCE_DENIED", b, facts(b))
    def test_b_restaurant_module_denied(self):
        b = fixture("payments_only", issued_b=True)
        b["modules"]["required"].append("R2_KITCHEN")
        self.blocked("PK_D2_RESTAURANT_MODULE_LEAK", b, facts(b))
    def test_b_restaurant_pack_conflict(self):
        b = fixture("payments_only", issued_b=True)
        b["packs"].append(copy.deepcopy(self.a["packs"][0]))
        self.blocked("PK_D2_INCOMPATIBLE_PACK_GRAPH", b, facts(b))
    def test_b_restaurant_template_conflict(self):
        b = fixture("payments_only", issued_b=True)
        b["template"]["code"]="restaurant.counter_service"
        self.blocked("PK_D2_TEMPLATE_PROFILE_CONFLICT", b, facts(b))
    def test_b_bad_provider(self):
        b = fixture("payments_only", issued_b=True)
        f=facts(b);f["policy"]["provider_status"]="DENIED"
        self.blocked("PK_D2_PROVIDER_NOT_ADMITTED", b, f)
    def test_b_provider_wrong_country(self):
        b = fixture("payments_only", issued_b=True)
        f=facts(b);f["policy"]["provider_countries"]=["SN"]
        self.blocked("PK_D2_PROVIDER_NOT_ADMITTED", b, f)
    def test_wrong_pack_alias(self):
        b=copy.deepcopy(self.a);b["pack_alias"]="PAYMENTS_ONLY"
        self.blocked("PK_D2_PACK_ALIAS_MISMATCH",b)
    def test_wrong_version(self):
        b=copy.deepcopy(self.a);b["packs"][0]["version"]="2.0.0"
        self.blocked("PK_D2_INCOMPATIBLE_PACK_GRAPH",b)
    def test_stale_pack_version_from_pk(self):
        f=copy.deepcopy(self.f);f["pk"]["packs"][0]["version"]="2.0.0"
        self.blocked("PK_D2_PK_PACK_VERSION_MISMATCH",source=f)
    def test_retired_pack(self):
        f=copy.deepcopy(self.f);f["pk"]["packs"][0]["status"]="RETIRED"
        self.blocked("PK_D2_PACK_RETIRED_UNCERTIFIED_OR_UNVERIFIED",source=f)
    def test_uncertified_pack(self):
        f=copy.deepcopy(self.f);f["pk"]["packs"][0]["certification"]="FAIL"
        self.blocked("PK_D2_PACK_RETIRED_UNCERTIFIED_OR_UNVERIFIED",source=f)
    def test_missing_nine_certification_axes(self):
        f=copy.deepcopy(self.f);f["pk"]["packs"][0]["passed_checks"]=["architecture"]
        self.blocked("PK_D2_PACK_RETIRED_UNCERTIFIED_OR_UNVERIFIED",source=f)
    def test_manifest_sha_conflict(self):
        b=copy.deepcopy(self.a);b["packs"][0]["manifest_sha256"]=sha("wrong")
        self.blocked("PK_D2_PACK_MANIFEST_CONFLICT",b)
    def test_wrong_country_pack(self):
        f=copy.deepcopy(self.f);f["pk"]["packs"][0]["eligible_countries"]=["SN"]
        self.blocked("PK_D2_PACK_COUNTRY_INELIGIBLE",source=f)
    def test_wrong_tax_policy(self):
        f=copy.deepcopy(self.f);f["policy"]["tax_eligible"]=False
        self.blocked("PK_D2_COUNTRY_OR_TAX_POLICY_DENIED",source=f)
    def test_country_mismatch_pc4(self):
        f=copy.deepcopy(self.f);f["pc4"]["country"]="GA"
        self.blocked("PK_D2_PC4_ENTITLEMENT_DENIED",source=f)
    def test_forged_merchant_binding(self):
        f=copy.deepcopy(self.f);f["pc1"]["merchant_public_uuid"]="fake"
        self.blocked("PK_D2_PC1_TENANT_BINDING_DENIED",source=f)
    def test_cross_tenant_readback(self):
        f=copy.deepcopy(self.f);f["pc1"]["tenant_id"]=2
        self.blocked("PK_D2_PC1_TENANT_BINDING_DENIED",source=f)
    def test_wrong_branch_pc5(self):
        f=copy.deepcopy(self.f);f["pc5"]["branch_id"]=6
        self.blocked("PK_D2_PC5_PRINCIPAL_OR_SCOPE_DENIED",source=f)
    def test_missing_owner_consent(self):
        f=copy.deepcopy(self.f);f["pa"]["owner_consent"]="PENDING"
        self.blocked("PK_D2_PA_CONSENT_OR_LIFECYCLE_DENIED",source=f)
    def test_inactive_subscription(self):
        f=copy.deepcopy(self.f);f["pa"]["subscription"]="PAUSED"
        self.blocked("PK_D2_PA_CONSENT_OR_LIFECYCLE_DENIED",source=f)
    def test_pc4_disabled(self):
        f=copy.deepcopy(self.f);f["pc4"]["subscription_entitled"]=False
        self.blocked("PK_D2_PC4_ENTITLEMENT_DENIED",source=f)
    def test_pc4_required_module_missing(self):
        f=copy.deepcopy(self.f);f["pc4"]["effective_modules"]=[]
        self.blocked("PK_D2_PC4_REQUIRED_MODULE_DENIED",source=f)
    def test_pc5_revoked(self):
        f=copy.deepcopy(self.f);f["pc5"]["revoked"]=True
        self.blocked("PK_D2_PC5_PRINCIPAL_OR_SCOPE_DENIED",source=f)
    def test_pc5_wrong_assurance(self):
        f=copy.deepcopy(self.f);f["pc5"]["assurance"]="OIDC_ONLY"
        self.blocked("PK_D2_PC5_PRINCIPAL_OR_SCOPE_DENIED",source=f)
    def test_pc5_missing_permission(self):
        f=copy.deepcopy(self.f);f["pc5"]["permissions"]=[]
        self.blocked("PK_D2_PC5_PRINCIPAL_OR_SCOPE_DENIED",source=f)
    def test_expired_snapshot(self):
        f=copy.deepcopy(self.f);f["pk"]["expires_at"]=TIME
        self.blocked("PK_D2_STALE_PK",source=f)
    def test_wrong_snapshot_producer(self):
        f=copy.deepcopy(self.f);f["pk"]["producer"]="PC4"
        self.blocked("PK_D2_WRONG_PRODUCER_PK",source=f)
    def test_non_test_grade_denied(self):
        f=copy.deepcopy(self.f);f["pk"]["proof_grade"]="REAL_HOSTED_GRANTED"
        self.blocked("PK_D2_UNVERIFIED_RUNTIME_READBACK_FORBIDDEN",source=f)
    def test_effective_claim_denied(self):
        b=copy.deepcopy(self.a);b["desired_vs_effective"]["effective"]=True
        self.blocked("PK_D2_FORGED_EFFECTIVE_STATUS",b)
    def test_raw_secret_denied(self):
        b=copy.deepcopy(self.a);b["client_secret"]="not-real"
        self.blocked("PK_D2_INLINE_SECRET_FORBIDDEN",b)
    def test_xafchat_off_skips_cert(self):
        v=compile_(self.a,self.f,xafchat_mode="off")
        self.assertEqual(v["optional_packs"],[])
    def test_xafchat_on_unrequested_denied(self):
        self.blocked("PK_D2_XAFCHAT_NOT_REQUESTED",xafchat_mode="on")
    def test_xafchat_pause_unrequested_denied(self):
        self.blocked("PK_D2_XAFCHAT_NOT_REQUESTED",xafchat_mode="pause")
    def test_xafchat_on_requested_uncertified(self):
        b=copy.deepcopy(self.a);b["channels"]["xafchat"]["requested"]=True
        self.blocked("PK_D2_XAFCHAT_PACK_NOT_CERTIFIED",b,facts(b),xafchat_mode="on")
    def test_xafchat_pause_skips_pack(self):
        b=copy.deepcopy(self.a);b["channels"]["xafchat"]["requested"]=True
        v=compile_(b,facts(b),xafchat_mode="pause")
        self.assertEqual(v["optional_packs"],[])
        self.assertEqual(v["xafchat_mode"],"pause")
    def test_xafchat_on_certified_hypothetical(self):
        b=copy.deepcopy(self.a);b["channels"]["xafchat"]["requested"]=True
        f=facts(b)
        f["pk"]["xafchat_optional_pack"]={
            "code":"communications.xafchat.SYNTHETIC", "version":"1.0.0",
            "manifest_sha256":sha("synthetic.xafchat.manifest"),
            "certification_evidence_sha256":sha("synthetic.xafchat.cert"),
            "certification":"PASS","status":"ACTIVE",
            "passed_checks":sorted(_REQUIRED_CERTIFICATION_CHECKS),
            "eligible_countries":["CM"]}
        f["pc4"]["xafchat_entitled"]=True
        f["policy"]["xafchat_connector_eligible"]=True
        v=compile_(b,f,xafchat_mode="on")
        self.assertEqual(len(v["optional_packs"]),1)
        self.assertFalse(v["activation_permitted"])
    def test_xafchat_connector_denied(self):
        b=copy.deepcopy(self.a);b["channels"]["xafchat"]["requested"]=True
        f=facts(b)
        f["pk"]["xafchat_optional_pack"]={
            "code":"communications.xafchat.SYNTHETIC", "version":"1.0.0",
            "manifest_sha256":sha("synthetic.xafchat.manifest"),
            "certification_evidence_sha256":sha("synthetic.xafchat.cert"),
            "certification":"PASS","status":"ACTIVE",
            "passed_checks":sorted(_REQUIRED_CERTIFICATION_CHECKS),
            "eligible_countries":["CM"]}
        f["pc4"]["xafchat_entitled"]=True
        self.blocked("PK_D2_XAFCHAT_CHANNEL_NOT_ELIGIBLE",b,f,xafchat_mode="on")
    def test_idempotent_replay_identical(self):
        v=compile_(self.a,self.f)
        original={"key":self.a["idempotency"]["command_key"],
                  "request_sha256":v["request_sha256"]}
        self.assertEqual(compile_(self.a,self.f,replay=original)["plan_sha256"],v["plan_sha256"])
    def test_idempotent_key_payload_collision(self):
        old={"key":self.a["idempotency"]["command_key"],"request_sha256":sha("different")}
        self.blocked("PK_D2_IDEMPOTENCY_PAYLOAD_CONFLICT",replay=old)
    def test_time_without_zone_denied(self):
        with self.assertRaises(ActivationPlanCompilationError) as e:
            compile_activation_plan(self.a,self.f,evaluated_at="2026-11-09T12:00:00")
        self.assertEqual(e.exception.code,"PK_D2_TIMEZONE_REQUIRED")
    def test_template_source_fingerprint_conflict(self):
        b=copy.deepcopy(self.a);b["template"]["template_sha256"]=sha("wrong-template")
        self.blocked("PK_D2_PK_TEMPLATE_HASH_CONFLICT",b)
    def test_certification_source_fingerprint_conflict(self):
        b=copy.deepcopy(self.a);b["packs"][0]["certification_evidence_ref"]=sha("wrong-cert")
        self.blocked("PK_D2_PACK_CERTIFICATION_CONFLICT",b)
    def test_restaurant_required_provider_denied(self):
        b=copy.deepcopy(self.a);b["channels"]["provider_checkout"]["required"]=True
        f=facts(b);f["policy"]["payment_connector_eligible"]=False
        self.blocked("PK_D2_PROVIDER_NOT_ADMITTED",b,f)
    def test_restaurant_optional_provider_does_not_block_cash_pos(self):
        f=copy.deepcopy(self.f);f["policy"]["payment_connector_eligible"]=False
        self.assertFalse(compile_(self.a,f)["activation_permitted"])

if __name__ == "__main__":
    unittest.main()
