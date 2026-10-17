from __future__ import annotations

import base64
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.integrations.xafpay_v2.attestation_client import (
    AttestationClientError,
    GATEWAY_ATTESTATION_PATH,
    GuardedAttestationClient,
    TransportResponse,
)
from core.integrations.xafpay_v2.attestation_service import (
    ATTESTATION_PERMISSION,
    ATTESTATION_PURPOSE,
    ATTESTATION_SCHEMA,
    GATEWAY_AUDIENCE,
    GATEWAY_ENVIRONMENT,
    PCR_EXECUTION_GRANT_SCHEMA,
    REQUIRED_CREDENTIAL_SCOPE,
    WND_ATTESTATION_TARGET,
    AttestationDenied,
    Ed25519WorkloadSigner,
    OperatorContext,
    PcrGrantVerifier,
    ReplayGuard,
    WndAttestationService,
    base64url_encode,
    canonical_attestation_json,
    sign_ed25519_for_test,
    validate_workload_envelope,
    verify_ed25519_signature,
)
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY


NOW = datetime(2026, 10, 17, 11, 0, 0, tzinfo=timezone.utc)
PCR_GRANT_ID = "11111111-1111-4111-8111-111111111111"
GATEWAY_GRANT_ID = "22222222-2222-4222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"
PCR_KEY_ID = "pcr-test-key"
WORKLOAD_KEY_ID = "wnd-test-key"
PCR_REFERENCE = "JOEL/XAFPAY_CEO"
WORKLOAD_REFERENCE = "DOROTHY/WND_MANAGER"
MOCK_CREDENTIAL = "xps_staging_mock.mocksecret"
MOCK_HOST = "gateway.test"


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _operator(
    *,
    tenant_id: int = 2,
    branch_id: int = 1,
    user_id: int = 7,
    role: str = "wnd_manager",
    permissions: frozenset[str] = frozenset({ATTESTATION_PERMISSION}),
    expires_at: datetime | None = None,
) -> OperatorContext:
    return OperatorContext(
        user_id=user_id,
        tenant_id=tenant_id,
        branch_id=branch_id,
        role=role,
        permissions=permissions,
        expires_at=expires_at or (NOW + timedelta(minutes=30)),
    )


def _grant(**overrides):
    value = {
        "schema": PCR_EXECUTION_GRANT_SCHEMA,
        "issuer_key_id": PCR_KEY_ID,
        "issuer_reference": PCR_REFERENCE,
        "grant_id": PCR_GRANT_ID,
        "gateway_grant_id": GATEWAY_GRANT_ID,
        "purpose": ATTESTATION_PURPOSE,
        "tenant_id": 2,
        "branch_id": 1,
        "operator_id": 7,
        "workload_reference": WORKLOAD_REFERENCE,
        "workload_key_id": WORKLOAD_KEY_ID,
        "target": dict(WND_ATTESTATION_TARGET),
        "issued_at": _iso(NOW - timedelta(seconds=10)),
        "expires_at": _iso(NOW + timedelta(minutes=2)),
    }
    for key, item in overrides.items():
        if key == "target":
            value["target"] = item
        else:
            value[key] = item
    return value


class MockCredentialProvider:
    def __init__(self, credential: str = MOCK_CREDENTIAL):
        self.credential = credential
        self.calls: list[tuple[str, str]] = []

    def get_credential(self, *, credential_id: str, environment: str) -> str:
        self.calls.append((credential_id, environment))
        return self.credential


class MockTransport:
    def __init__(
        self,
        *,
        workload_public_key: bytes,
        mode: str = "ok",
        expected_grant_id: str = GATEWAY_GRANT_ID,
    ):
        self.workload_public_key = workload_public_key
        self.mode = mode
        self.expected_grant_id = expected_grant_id
        self.calls = 0
        self.last_body: dict | None = None
        self.last_envelope: dict | None = None

    def post(
        self,
        *,
        url: str,
        headers,
        content: bytes,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> TransportResponse:
        self.calls += 1
        assert url == f"https://{MOCK_HOST}{GATEWAY_ATTESTATION_PATH}"
        assert timeout_seconds == 3.0
        assert follow_redirects is False
        assert set(headers) == {
            "Content-Type",
            "X-XafPay-Workload-Envelope",
            "X-XafPay-Workload-Signature",
        }

        if self.mode == "timeout":
            raise TimeoutError("mock timeout")

        encoded = headers["X-XafPay-Workload-Envelope"]
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        raw_envelope = base64.urlsafe_b64decode(encoded + padding)
        envelope = json.loads(raw_envelope.decode("utf-8"))
        assert raw_envelope == canonical_attestation_json(envelope)
        assert verify_ed25519_signature(
            envelope,
            headers["X-XafPay-Workload-Signature"],
            self.workload_public_key,
        )

        body = json.loads(content.decode("utf-8"))
        assert set(body) == {"grant_id", "credential"}
        assert body["grant_id"] == self.expected_grant_id
        assert body["credential"] == MOCK_CREDENTIAL
        assert envelope["body_sha256"]
        self.last_body = body
        self.last_envelope = envelope

        checks = {
            "secret_valid": True,
            "credential_id_match": True,
            "merchant_match": True,
            "subject_match": True,
            "audience_match": True,
            "environment_match": True,
            "lifecycle_valid": True,
            "scope_valid": True,
        }
        response = {
            "schema": "xafpay.wnd.credential-binding-attestation-result.v1",
            "grant_id": self.expected_grant_id,
            "full_binding": self.mode != "binding_false",
            "checks": checks,
        }

        if self.mode == "redirect":
            return TransportResponse(
                status_code=302,
                body=b"",
                headers={"Location": "https://evil.test/"},
                url=url,
            )
        if self.mode == "cross_host":
            return TransportResponse(
                status_code=200,
                body=json.dumps(response).encode(),
                headers={},
                url=f"https://evil.test{GATEWAY_ATTESTATION_PATH}",
            )
        return TransportResponse(
            status_code=200,
            body=json.dumps(response).encode(),
            headers={},
            url=url,
        )


def _bundle(*, transport_mode: str = "ok", verifier_key: bytes | None = None):
    pcr_private = Ed25519PrivateKey.generate()
    workload_private = Ed25519PrivateKey.generate()
    provider = MockCredentialProvider()
    transport = MockTransport(
        workload_public_key=_raw_public(workload_private),
        mode=transport_mode,
    )
    client = GuardedAttestationClient(
        base_url=f"https://{MOCK_HOST}",
        allowed_hosts=frozenset({MOCK_HOST}),
        transport=transport,
        timeout_seconds=3.0,
    )
    verifier = PcrGrantVerifier(
        issuer_public_keys={
            PCR_KEY_ID: verifier_key if verifier_key is not None else _raw_public(pcr_private)
        },
        expected_issuer_reference=PCR_REFERENCE,
        expected_workload_reference=WORKLOAD_REFERENCE,
    )
    service = WndAttestationService(
        enabled=True,
        grant_verifier=verifier,
        workload_signer=Ed25519WorkloadSigner(
            key_id=WORKLOAD_KEY_ID,
            private_key=workload_private,
        ),
        credential_provider=provider,
        client=client,
        clock=lambda: NOW,
        request_id_factory=lambda: REQUEST_ID,
        replay_guard=ReplayGuard(),
    )
    grant = _grant()
    signature = sign_ed25519_for_test(grant, pcr_private)
    return service, grant, signature, pcr_private, workload_private, provider, transport


def _resign(grant: dict, private_key: Ed25519PrivateKey) -> str:
    return sign_ed25519_for_test(grant, private_key)


def _deny_code(callable_):
    with pytest.raises(AttestationDenied) as caught:
        callable_()
    return caught.value.code


def test_valid_mock_attestation_is_purpose_bound_and_secret_free():
    service, grant, signature, _, _, provider, transport = _bundle()

    result = service.execute(
        operator=_operator(),
        grant_value=grant,
        grant_signature=signature,
    )

    assert result["full_binding"] is True
    assert result["purpose"] == ATTESTATION_PURPOSE
    assert result["tenant_id"] == 2
    assert result["branch_id"] == 1
    assert result["operator_id"] == 7
    assert result["request_id"] == REQUEST_ID
    assert "credential" not in result
    assert provider.calls == [
        (
            WND_ATTESTATION_TARGET["credential_id"],
            GATEWAY_ENVIRONMENT,
        )
    ]
    assert transport.calls == 1
    assert transport.last_envelope["schema"] == ATTESTATION_SCHEMA
    assert transport.last_envelope["http_method"] == "POST"
    assert transport.last_envelope["exact_path"] == GATEWAY_ATTESTATION_PATH
    assert transport.last_envelope["gateway_audience"] == GATEWAY_AUDIENCE
    assert transport.last_envelope["target"] == dict(WND_ATTESTATION_TARGET)
    assert transport.last_envelope["grant_id"] == GATEWAY_GRANT_ID


def test_gateway_jcs_vectors_match_accepted_contract():
    assert canonical_attestation_json({"z": 1, "a": "test"}) == b'{"a":"test","z":1}'
    vector = {
        "\U0001f600": 1,
        "a": 2,
        "numbers": [333333333.33333329, 1e30, 4.5, 0.002, 1e-27],
    }
    assert canonical_attestation_json(vector).decode("utf-8") == (
        '{"a":2,"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"😀":1}'
    )


@pytest.mark.parametrize("bad", [{"bad": "\ud800"}, {"bad": float("nan")}, {"bad": float("inf")}])
def test_canonicalization_rejects_malformed_or_nonfinite_values(bad):
    assert _deny_code(lambda: canonical_attestation_json(bad)) == (
        "ATTESTATION_CANONICALIZATION_INVALID"
    )


def test_ed25519_signature_rejects_mutation_and_wrong_public_key():
    private = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    message = {"method": "POST", "purpose": ATTESTATION_PURPOSE}
    signature = sign_ed25519_for_test(message, private)

    assert verify_ed25519_signature(message, signature, _raw_public(private))
    assert not verify_ed25519_signature(
        {**message, "method": "GET"},
        signature,
        _raw_public(private),
    )
    assert not verify_ed25519_signature(message, signature, _raw_public(other))


def test_missing_operator_is_denied():
    service, grant, signature, *_ = _bundle()
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(user_id=0),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_OPERATOR_MISSING"


@pytest.mark.parametrize(
    "permissions",
    [
        frozenset(),
        frozenset({"payments.receive"}),
        frozenset({"*"}),
        frozenset({"*", "payments.receive"}),
    ],
)
def test_missing_exact_permission_and_wildcard_only_are_denied(permissions):
    service, grant, signature, *_ = _bundle()
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(permissions=permissions),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PERMISSION_REQUIRED"


def test_superadmin_role_does_not_bypass_wrong_purpose():
    service, grant, _, pcr_private, *_ = _bundle()
    grant["purpose"] = "payments.receive"
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(role="superadmin"),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_GRANT_PURPOSE_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [("tenant_id", 999), ("branch_id", 999), ("operator_id", 999)],
)
def test_grant_must_match_exact_operator_tenant_branch(field, value):
    service, grant, _, pcr_private, *_ = _bundle()
    grant[field] = value
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_OPERATOR_SCOPE_MISMATCH"


def test_missing_pcr_grant_is_denied_before_transport():
    service, _, _, *_, transport = _bundle()
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=None,
            grant_signature="",
        )
    ) == "ATTESTATION_PCR_GRANT_MISSING"
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("target_field", "bad_value"),
    [
        ("merchant_id", "mch_wrong"),
        ("credential_id", "00000000-0000-4000-8000-000000000000"),
        ("audience", "wrong-gateway"),
        ("required_scope", "payments:create"),
        ("environment", "PRODUCTION"),
        ("subject", "other"),
    ],
)
def test_exact_gateway_target_cannot_be_overridden(target_field, bad_value):
    service, grant, _, pcr_private, *_ = _bundle()
    target = deepcopy(grant["target"])
    target[target_field] = bad_value
    grant["target"] = target
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_GRANT_TARGET_MISMATCH"


def test_wrong_pcr_signature_is_denied():
    service, grant, _, *_ = _bundle()
    wrong = Ed25519PrivateKey.generate()
    bad_signature = _resign(grant, wrong)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=bad_signature,
        )
    ) == "ATTESTATION_PCR_SIGNATURE_INVALID"


def test_wrong_pcr_public_key_is_denied():
    wrong_public = _raw_public(Ed25519PrivateKey.generate())
    service, grant, signature, *_ = _bundle(verifier_key=wrong_public)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_SIGNATURE_INVALID"


def test_unknown_pcr_key_is_denied():
    service, grant, _, pcr_private, workload_private, provider, transport = _bundle()
    grant["issuer_key_id"] = "unknown-pcr-key"
    signature = _resign(grant, pcr_private)
    verifier = PcrGrantVerifier(
        issuer_public_keys={PCR_KEY_ID: _raw_public(pcr_private)},
        expected_issuer_reference=PCR_REFERENCE,
        expected_workload_reference=WORKLOAD_REFERENCE,
    )
    replacement = WndAttestationService(
        enabled=True,
        grant_verifier=verifier,
        workload_signer=Ed25519WorkloadSigner(
            key_id=WORKLOAD_KEY_ID,
            private_key=workload_private,
        ),
        credential_provider=provider,
        client=GuardedAttestationClient(
            base_url=f"https://{MOCK_HOST}",
            allowed_hosts=frozenset({MOCK_HOST}),
            transport=transport,
        ),
        clock=lambda: NOW,
        request_id_factory=lambda: REQUEST_ID,
    )
    assert _deny_code(
        lambda: replacement.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_KEY_UNKNOWN"


def test_wrong_issuer_reference_is_denied():
    service, grant, _, pcr_private, *_ = _bundle()
    grant["issuer_reference"] = "NOT_PCR"
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_ISSUER_INVALID"


def test_wrong_workload_reference_and_key_are_denied():
    service, grant, _, pcr_private, *_ = _bundle()
    grant["workload_reference"] = "NOT_WND"
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_WND_WORKLOAD_INVALID"

    service, grant, _, pcr_private, *_ = _bundle()
    grant["workload_key_id"] = "different-workload-key"
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_WORKLOAD_KEY_MISMATCH"


def test_expired_and_revoked_grants_are_denied():
    service, grant, _, pcr_private, *_ = _bundle()
    grant["expires_at"] = _iso(NOW - timedelta(seconds=1))
    signature = _resign(grant, pcr_private)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_GRANT_EXPIRED"

    service, grant, _, pcr_private, workload_private, provider, transport = _bundle()
    signature = _resign(grant, pcr_private)
    verifier = PcrGrantVerifier(
        issuer_public_keys={PCR_KEY_ID: _raw_public(pcr_private)},
        expected_issuer_reference=PCR_REFERENCE,
        expected_workload_reference=WORKLOAD_REFERENCE,
        revoked_grant_ids=frozenset({PCR_GRANT_ID}),
    )
    replacement = WndAttestationService(
        enabled=True,
        grant_verifier=verifier,
        workload_signer=Ed25519WorkloadSigner(
            key_id=WORKLOAD_KEY_ID,
            private_key=workload_private,
        ),
        credential_provider=provider,
        client=GuardedAttestationClient(
            base_url=f"https://{MOCK_HOST}",
            allowed_hosts=frozenset({MOCK_HOST}),
            transport=transport,
        ),
        clock=lambda: NOW,
        request_id_factory=lambda: REQUEST_ID,
    )
    assert _deny_code(
        lambda: replacement.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_PCR_GRANT_REVOKED"


def test_envelope_body_digest_and_expired_timestamp_fail_closed():
    body = canonical_attestation_json(
        {"grant_id": GATEWAY_GRANT_ID, "credential": MOCK_CREDENTIAL}
    )
    envelope = {
        "schema": ATTESTATION_SCHEMA,
        "http_method": "POST",
        "exact_path": GATEWAY_ATTESTATION_PATH,
        "gateway_audience": GATEWAY_AUDIENCE,
        "grant_id": GATEWAY_GRANT_ID,
        "purpose": ATTESTATION_PURPOSE,
        "request_id": REQUEST_ID,
        "issued_at": _iso(NOW - timedelta(seconds=10)),
        "expires_at": _iso(NOW + timedelta(seconds=20)),
        "target": dict(WND_ATTESTATION_TARGET),
        "body_sha256": __import__("hashlib").sha256(body).hexdigest(),
        "workload_key_id": WORKLOAD_KEY_ID,
    }

    assert _deny_code(
        lambda: validate_workload_envelope(
            envelope,
            body=body + b" ",
            expected_workload_key_id=WORKLOAD_KEY_ID,
            now=NOW,
        )
    ) == "ATTESTATION_BODY_DIGEST_MISMATCH"

    expired = dict(envelope)
    expired["issued_at"] = _iso(NOW - timedelta(seconds=70))
    expired["expires_at"] = _iso(NOW - timedelta(seconds=1))
    assert _deny_code(
        lambda: validate_workload_envelope(
            expired,
            body=body,
            expected_workload_key_id=WORKLOAD_KEY_ID,
            now=NOW,
        )
    ) == "ATTESTATION_TIMESTAMP_EXPIRED"


def test_replayed_nonce_is_denied_and_never_replayed_on_transport():
    service, grant, signature, *_, transport = _bundle()
    first = service.execute(
        operator=_operator(),
        grant_value=grant,
        grant_signature=signature,
    )
    assert first["full_binding"] is True
    assert transport.calls == 1

    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == "ATTESTATION_REQUEST_REPLAYED"
    assert transport.calls == 1


def test_http_url_and_non_allowlisted_host_are_rejected():
    transport = MockTransport(workload_public_key=b"x" * 32)
    with pytest.raises(AttestationClientError) as http_error:
        GuardedAttestationClient(
            base_url="http://gateway.test",
            allowed_hosts=frozenset({MOCK_HOST}),
            transport=transport,
        )
    assert http_error.value.code == "ATTESTATION_HTTPS_TARGET_INVALID"

    with pytest.raises(AttestationClientError) as host_error:
        GuardedAttestationClient(
            base_url="https://other.test",
            allowed_hosts=frozenset({MOCK_HOST}),
            transport=transport,
        )
    assert host_error.value.code == "ATTESTATION_HTTPS_TARGET_INVALID"


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("redirect", "ATTESTATION_REDIRECT_REJECTED"),
        ("cross_host", "ATTESTATION_RESPONSE_ORIGIN_MISMATCH"),
        ("timeout", "ATTESTATION_TRANSPORT_TIMEOUT"),
        ("binding_false", "ATTESTATION_BINDING_FAILED"),
    ],
)
def test_transport_failures_fail_closed_without_retry(mode, expected_code):
    service, grant, signature, *_, transport = _bundle(transport_mode=mode)
    assert _deny_code(
        lambda: service.execute(
            operator=_operator(),
            grant_value=grant,
            grant_signature=signature,
        )
    ) == expected_code
    assert transport.calls == 1


def test_default_service_is_deny_and_makes_no_transport_call():
    disabled = WndAttestationService.disabled()
    assert _deny_code(
        lambda: disabled.execute(
            operator=_operator(),
            grant_value=_grant(),
            grant_signature="not-used",
        )
    ) == "ATTESTATION_FEATURE_DISABLED"


def test_exact_route_permission_is_registered_and_not_payment_permission():
    route = "/kernel/payments/xafpay/attestation/execute"
    assert PERMISSION_REGISTRY.resolve(route, "POST") == ATTESTATION_PERMISSION
    assert PERMISSION_REGISTRY.resolve(route, "GET") is None
    assert ATTESTATION_PERMISSION != "payments.receive"
