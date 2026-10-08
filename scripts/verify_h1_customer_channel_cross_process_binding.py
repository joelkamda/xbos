from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
MANIFEST = ROOT / "contracts/restaurant/v1/h1_release_manifest.json"
CONTRACT = ROOT / "contracts/restaurant/v1/h1_customer_channel_cross_process_binding.json"

EXPECTED_PATHS = {
    "restaurant/customer_channel/__init__.py",
    "restaurant/customer_channel/contracts.py",
    "restaurant/customer_channel/auth.py",
    "restaurant/customer_channel/delivery_policy.py",
    "restaurant/customer_channel/repository.py",
    "restaurant/customer_channel/adapters.py",
    "restaurant/customer_channel/service.py",
    "restaurant/customer_channel/router.py",
    "startup.py",
    "core/middleware/auth_middleware.py",
    "core/platform/interaction/sql_repository.py",
    "alembic_neutral/versions/cch_customer_channel_checkout_authority_047.py",
    "alembic_neutral/sql/cch_customer_channel_checkout_authority_up.sql",
    "alembic_neutral/sql/cch_customer_channel_checkout_authority_down.sql",
    "contracts/restaurant/v1/h1_customer_channel_cross_process_binding.json",
    "contracts/restaurant/v1/h1_release_manifest.json",
    "scripts/verify_h1_customer_channel_cross_process_binding.py",
    "tests/contracts/test_h1_customer_channel_cross_process_binding.py",
    "core/middleware/tenant_middleware.py",
    "core/middleware/branch_middleware.py",
    "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json",
    "contracts/platform/v1/pc8_release_manifest.json",
    "scripts/verify_pc8_h1b_private_route_admission_successor.py",
    "tests/contracts/test_pc8_h1b_private_route_admission_successor.py",
    "scripts/verify_pc7_neutral_interaction_authority.py",
    "tests/contracts/test_pc7_cumulative_release_manifest_chain.py",
}
CASES = [
    "service_auth_missing",
    "service_auth_wrong_principal",
    "service_scope_missing",
    "service_credential_rotation_current",
    "service_credential_rotation_next",
    "caller_tenant_override_forbidden",
    "caller_organization_override_forbidden",
    "cross_tenant_context_denial",
    "context_binding_missing_or_expired",
    "context_binding_wrong_purpose",
    "dine_in_valid_table",
    "dine_in_invalid_or_stale_table",
    "takeaway_contact_required",
    "takeaway_contact_authority",
    "delivery_contact_and_address_required",
    "delivery_address_binding_authority",
    "delivery_service_area_unavailable",
    "delivery_service_area_ambiguous_fail_closed",
    "delivery_fee_xbos_authoritative",
    "delivery_fee_so1_price_mismatch_fail_closed",
    "delivery_fee_materialized_into_r1_obligation_and_c3_amount",
    "channel_amount_total_fee_override_forbidden",
    "priced_modifier_not_in_c3_obligation_fail_closed",
    "confirmation_snapshot_durable",
    "stale_quote_reconfirmation",
    "confirmation_expiry",
    "confirmation_material_change",
    "submission_exact_retry",
    "submission_same_ref_different_confirmation_conflict",
    "confirmation_different_client_ref_conflict",
    "lost_response_reconciliation",
    "unknown_order_result",
    "c3_exact_replay",
    "c3_changed_fingerprint",
    "exact_customer_safe_projection",
    "no_private_identifiers",
    "unsupported_method",
    "no_payment_intent_no_gateway_no_provider",
    "no_paid_mapping_no_accounting_no_treasury",
    "legacy_kernel_orders_not_used",
]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("FAIL: " + message)


def status_paths() -> set[str]:
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "diff", "--name-only", BASE],
        text=True,
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard"],
        text=True,
    ).splitlines()
    return {
        value.strip().replace("\\", "/")
        for value in (*tracked, *untracked)
        if value.strip()
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    require(manifest["base_head"] == BASE, "manifest base head")
    require(set(manifest["authorized_paths"]) == EXPECTED_PATHS, "manifest corrective 26-path set")
    require(len(manifest["authorized_paths"]) == 26, "authorized path count")
    require(manifest["route_count"] == 4, "route count")
    require(manifest["acceptance_case_count"] == 40, "acceptance case count")
    require(manifest["financial_effect"] == "ZERO", "financial effect")

    actual = status_paths()
    require(actual <= EXPECTED_PATHS, f"unauthorized changed paths: {sorted(actual-EXPECTED_PATHS)}")

    migration = read("alembic_neutral/versions/cch_customer_channel_checkout_authority_047.py")
    require('revision = "cch_customer_channel_checkout_authority_047"' in migration, "047 revision")
    require('down_revision = "r1_restaurant_order_line_lifecycle_046"' in migration, "047 parent")

    up = read("alembic_neutral/sql/cch_customer_channel_checkout_authority_up.sql")
    require(up.count("CREATE TABLE public.") == 2, "exactly two new tables")
    require("CREATE TABLE public.restaurant_customer_delivery_policies" in up, "delivery table")
    require("CREATE TABLE public.restaurant_customer_order_confirmations" in up, "confirmation table")
    require("uq_cc_confirmation_claimed_submit" in up, "durable submit claim uniqueness")
    require("restaurant_customer_confirmation_immutable" in up, "immutable confirmation trigger")

    auth = read("restaurant/customer_channel/auth.py")
    require("hashlib.sha256" in auth and "hmac.compare_digest" in auth, "digest auth")
    require("TOKEN_DIGEST_CURRENT_ENV" in auth and "TOKEN_DIGEST_NEXT_ENV" in auth, "credential rotation")

    middleware = read("core/middleware/auth_middleware.py")
    require('path.startswith("/internal/customer-channel/v1")' in middleware, "human JWT bypass reservation")
    tenant_middleware = read("core/middleware/tenant_middleware.py")
    branch_middleware = read("core/middleware/branch_middleware.py")
    require('path.startswith("/internal/customer-channel/v1")' in tenant_middleware, "private tenant middleware bypass")
    require('path.startswith("/internal/customer-channel/v1")' in branch_middleware, "private branch middleware bypass")

    interaction = read("core/platform/interaction/sql_repository.py")
    require("def context_binding_by_public_id(" in interaction, "IA0 public-id read")
    require("IA0_CONTEXT_BINDING_AMBIGUOUS" in interaction, "cross-tenant ambiguity guard")

    router = read("restaurant/customer_channel/router.py")
    for token in (
        '@router.post("/order-confirmations")',
        '@router.post("/orders")',
        '@router.get("/orders/by-client-submit-ref/{client_submit_ref}")',
        '@router.post("/orders/{order_ref}/payment-request")',
    ):
        require(token in router, "missing route " + token)
    require("/kernel/orders" not in router, "legacy kernel orders reused")

    service = read("restaurant/customer_channel/service.py")
    for token in (
        "cc1:{submit_hash}:submit",
        "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
        "create_payment_request",
    ):
        require(token in service, "missing service law " + token)
    repository = read("restaurant/customer_channel/repository.py")
    require("claimed_client_submit_ref_hash" in repository, "missing durable confirmation claim law")
    require("create_intent(" not in service, "payment intent creation forbidden")
    require("create_attempt(" not in service, "payment attempt creation forbidden")

    adapters = read("restaurant/customer_channel/adapters.py")
    require("CustomerSafeCheckoutPaymentRequestService" in adapters, "C3 transport composition")
    require("XafPayGatewayV2ExecutionAdapter" not in adapters, "gateway execution imported")
    require("create_payment(" not in adapters, "gateway payment call")
    require("Decimal(price.amount) != Decimal(\"0\")" in adapters, "priced modifier guard")

    startup = read("startup.py")
    require("customer_channel_router" in startup, "private router mount")

    require(contract["private_route_prefix"] == "/internal/customer-channel/v1", "private prefix contract")
    require(contract["migration"]["down_revision"] == "r1_restaurant_order_line_lifecycle_046", "contract migration parent")
    require(contract["financial_effect"] == "ZERO", "contract financial firewall")
    require(contract["c3"]["payment_execution"] is False, "C3 execution firewall")
    require(len(contract["c3"]["response_fields"]) == 13, "exact C3 projection field count")

    tests = read("tests/contracts/test_h1_customer_channel_cross_process_binding.py")
    missing = [case for case in CASES if f"test_{case}" not in tests]
    require(not missing, "missing 40-case tests: " + ",".join(missing))

    print(json.dumps({
        "status": "PASS",
        "base_head": BASE,
        "authorized_path_count": len(EXPECTED_PATHS),
        "current_changed_path_count": len(actual),
        "migration_revision": "cch_customer_channel_checkout_authority_047",
        "migration_parent": "r1_restaurant_order_line_lifecycle_046",
        "new_table_count": 2,
        "route_count": 4,
        "acceptance_case_count": 40,
        "legacy_kernel_orders_reused": False,
        "payment_intent_creation": False,
        "gateway_call": False,
        "provider_call": False,
        "financial_effect": "ZERO",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
