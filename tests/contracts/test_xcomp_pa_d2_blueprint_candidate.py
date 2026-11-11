"""D2 PA pure-source, deliberately nonoperative negatives."""
import copy
import pytest
from platform_admin.xcomp_blueprint_d2_candidate import (
    accept_blueprint, evaluate_readiness, BlueprintRejected, AuthorityReadback,
)


def blueprint(profile="restaurant"):
    restaurant = profile == "restaurant"
    return {
        "schema": "xcomp.MerchantBlueprint.v1",
        "nonoperative": True,
        "actual_d2_activation_authorized": False,
        "blueprint_id": "BP-TEST-1",
        "revision": 1,
        "idempotency": {"command_key": "bp:test:revision:1"},
        "merchant_profile": profile,
        "tenant": {"numeric_id": 910001 if restaurant else None,
                   "merchant_public_uuid": "4b196022-55a1-548c-b122-f1f9e4b78bea" if restaurant else None},
        "packs": [{"code": x, "manifest_sha256": None, "certification_evidence_ref": None}
                  for x in (["industry.restaurant"] if restaurant else ["neutral.foundation", "neutral.payments"])],
        "template": {"code": "restaurant.counter_service" if restaurant else "neutral.payments_only"},
        "owner_consent": {"state": "PENDING", "proof_ref": None},
        "business_policy": {"finance_kernel_required": True, "tenant_overrides":
            {"business_day_start": "08:00" if restaurant else None, "kitchen": "FOOD_ONLY" if restaurant else None}},
        "desired_vs_effective": {"requested": "D0_TEST", "effective": False},
    }


def receipts():
    return {
        issuer: AuthorityReadback(issuer, 910001, "4b196022-55a1-548c-b122-f1f9e4b78bea",
                                  "principal-01", issuer.lower()+":evidence:1", 3000, True, True, 2)
        for issuer in ("PC1", "PK", "PC4", "PC5", "PA")
    }


def evaluate(bp=None, proofs=None, **kwargs):
    return evaluate_readiness(accept_blueprint(bp or blueprint()), proofs if proofs is not None else receipts(),
                              authenticated_principal=kwargs.pop("authenticated_principal", "principal-01"),
                              requested_tenant=kwargs.pop("requested_tenant", 910001),
                              now_epoch=kwargs.pop("now_epoch", 1000), **kwargs)


def test_canonical_revision_digest_repeatable_and_snapshot_immutable():
    value=blueprint()
    accepted=accept_blueprint(value)
    value["template"]["code"]="tampered"
    assert accepted == accept_blueprint(blueprint())
    assert accepted.digest != accept_blueprint({**blueprint(),"revision":2}).digest


def test_positive_receipts_never_operational():
    result=evaluate()
    assert result.state=="SOURCE_PREFLIGHT_ONLY" and result.effective is False


@pytest.mark.parametrize("mutation,code",[
    (lambda x:x.update(schema="other"),"SCHEMA_MISMATCH"),
    (lambda x:x.update(nonoperative=False),"OPERATIVE_CLAIM"),
    (lambda x:x["tenant"].update(numeric_id=2),"SYNTHETIC_RESTAURANT_BINDING"),
    (lambda x:x["packs"][0].update(certification_evidence_ref="pk:forged:1"),"UNVERIFIED_PACK_CLAIM"),
    (lambda x:x["packs"][0].update(code="restaurant.counter_service"),"TEMPLATE_AS_PACK"),
    (lambda x:x["owner_consent"].update(state="APPROVED"),"EFFECTIVE_OR_CONSENT_CLAIM"),
    (lambda x:x["desired_vs_effective"].update(effective=True),"EFFECTIVE_OR_CONSENT_CLAIM"),
    (lambda x:x.update(provider_secret="very-private"),"RAW_SECRET_FIELD"),
])
def test_blueprint_negative(mutation,code):
    value=blueprint()
    mutation(value)
    with pytest.raises(BlueprintRejected,match=code):
        accept_blueprint(value)


def test_unissued_payments_only_is_never_ready():
    b=blueprint("payments_only")
    assert accept_blueprint(b).tenant_id is None
    assert "TENANT_UNISSUED" in evaluate(b).reasons


def test_restaurant_policy_cannot_leak_to_payments_only():
    b=blueprint("payments_only")
    b["business_policy"]["tenant_overrides"]["business_day_start"]="08:00"
    with pytest.raises(BlueprintRejected,match="RESTAURANT_POLICY_LEAK"):
        accept_blueprint(b)


@pytest.mark.parametrize("issuer,changed,expected",[
    ("PC1", {"tenant_id":2}, "PC1_SCOPE_MISMATCH"),
    ("PK", {"active":False}, "PK_DENIED_OR_EXPIRED"),
    ("PC4", {"expires_at":1000}, "PC4_DENIED_OR_EXPIRED"),
    ("PC5", {"assurance_level":1}, "PC5_INSUFFICIENT_ASSURANCE"),
    ("PA", {"authorized":False}, "PA_DENIED_OR_EXPIRED"),
    ("PC5", {"principal_ref":"forged-operator"}, "PC5_PRINCIPAL_MISMATCH"),
])
def test_independent_producer_denials(issuer,changed,expected):
    proofs=receipts()
    original=proofs[issuer]
    proofs[issuer]=AuthorityReadback(**{**original.__dict__, **changed})
    assert expected in evaluate(proofs=proofs).reasons


def test_missing_proof_fails_closed():
    proofs=receipts()
    del proofs["PK"]
    assert "PK_PROOF_MISSING" in evaluate(proofs=proofs).reasons


def test_unauthenticated_and_cross_tenant():
    reasons=evaluate(authenticated_principal=None,requested_tenant=11).reasons
    assert "UNAUTHENTICATED" in reasons and "WRONG_TENANT" in reasons


def test_idempotency_changed_digest_rejected():
    assert "IDEMPOTENCY_CONFLICT" in evaluate(prior_command_digest="0"*64).reasons


def test_duplicate_identical_request_is_only_preflight():
    digest=accept_blueprint(blueprint()).digest
    assert evaluate(prior_command_digest=digest).state=="SOURCE_PREFLIGHT_ONLY"
