import pytest


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


EXPECTED_METHODS = {
    "/kernel/auth/login": {"post"},
    "/kernel/orders/": {"get", "post"},
    "/kernel/sales/": {"get", "post"},
    "/kernel/sales/{sale_id}": {"get"},
    "/kernel/payments/pos/settle": {"post"},
    "/kernel/payments/receipts/{sale_id}": {"get"},
    "/kernel/accounting/accounts/ar/{ar_id}/repay": {"post"},
    "/kernel/accounting/reconciliation": {"get"},
    "/kernel/accounting/reconciliation/save-draft": {"post"},
    "/kernel/accounting/reconciliation/close": {"post"},
}


def test_legacy_financial_api_paths_are_preserved(app):
    schema = app.openapi()
    paths = schema["paths"]

    for path, expected_methods in EXPECTED_METHODS.items():
        assert path in paths
        actual_methods = {
            method
            for method in paths[path]
            if method in {"get", "post", "put", "patch", "delete"}
        }
        assert expected_methods <= actual_methods


def test_legacy_untyped_financial_payloads_are_preserved(app):
    schema = app.openapi()

    sale_payload = schema["paths"]["/kernel/sales/"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]

    settlement_payload = schema["paths"]["/kernel/payments/pos/settle"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]

    assert sale_payload["type"] == "object"
    assert sale_payload["additionalProperties"] is True

    assert settlement_payload["type"] == "object"
    assert settlement_payload["additionalProperties"] is True