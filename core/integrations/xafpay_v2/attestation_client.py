"""Guarded, injection-only client for WND credential attestation redemption.

This module intentionally contains no live HTTP implementation.  R4-W qualification
must inject a mock transport; future live transport admission is a separate gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.parse import urlparse

GATEWAY_ATTESTATION_PATH = "/internal/wnd-credential-attestations/v1/redeem"
GATEWAY_ATTESTATION_RESULT_SCHEMA = (
    "xafpay.wnd.credential-binding-attestation-result.v1"
)


class AttestationClientError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    url: str


class AttestationTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        content: bytes,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> TransportResponse: ...


class GuardedAttestationClient:
    """Exact-host HTTPS client contract with one injected transport call."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: frozenset[str],
        transport: AttestationTransport,
        timeout_seconds: float = 3.0,
    ):
        parsed = urlparse(str(base_url).strip())
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or host not in {value.lower() for value in allowed_hosts}
        ):
            raise AttestationClientError("ATTESTATION_HTTPS_TARGET_INVALID")
        if not (0.1 <= float(timeout_seconds) <= 10.0):
            raise AttestationClientError("ATTESTATION_TIMEOUT_INVALID")

        self._base_url = f"https://{parsed.netloc}".rstrip("/")
        self._netloc = parsed.netloc.lower()
        self._host = host
        self._allowed_hosts = frozenset(value.lower() for value in allowed_hosts)
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)

    @property
    def exact_url(self) -> str:
        return self._base_url + GATEWAY_ATTESTATION_PATH

    def redeem(
        self,
        *,
        body: bytes,
        workload_envelope: str,
        workload_signature: str,
        grant_id: str,
    ) -> dict:
        if not body or len(body) > 4096:
            raise AttestationClientError("ATTESTATION_BODY_INVALID")
        if not workload_envelope or not workload_signature:
            raise AttestationClientError("ATTESTATION_SIGNATURE_HEADERS_INVALID")

        # One call only. There is deliberately no retry loop or fallback URL.
        try:
            response = self._transport.post(
                url=self.exact_url,
                headers={
                    "Content-Type": "application/json",
                    "X-XafPay-Workload-Envelope": workload_envelope,
                    "X-XafPay-Workload-Signature": workload_signature,
                },
                content=body,
                timeout_seconds=self._timeout_seconds,
                follow_redirects=False,
            )
        except TimeoutError as exc:
            raise AttestationClientError("ATTESTATION_TRANSPORT_TIMEOUT") from exc
        except Exception as exc:
            raise AttestationClientError("ATTESTATION_TRANSPORT_FAILED") from exc

        if 300 <= int(response.status_code) <= 399:
            raise AttestationClientError("ATTESTATION_REDIRECT_REJECTED")

        response_url = urlparse(str(response.url))
        if (
            response_url.scheme != "https"
            or (response_url.hostname or "").lower() != self._host
            or response_url.netloc.lower() != self._netloc
            or response_url.path != GATEWAY_ATTESTATION_PATH
            or response_url.query
            or response_url.fragment
        ):
            raise AttestationClientError("ATTESTATION_RESPONSE_ORIGIN_MISMATCH")

        if not (200 <= int(response.status_code) <= 299):
            raise AttestationClientError("ATTESTATION_GATEWAY_REJECTED")

        try:
            payload = json.loads(bytes(response.body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID") from exc

        if not isinstance(payload, dict):
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID")

        expected_keys = {"schema", "grant_id", "full_binding", "checks"}
        if set(payload) != expected_keys:
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID")
        if payload.get("schema") != GATEWAY_ATTESTATION_RESULT_SCHEMA:
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID")
        if payload.get("grant_id") != grant_id:
            raise AttestationClientError("ATTESTATION_GRANT_ID_MISMATCH")
        if not isinstance(payload.get("full_binding"), bool):
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID")

        checks = payload.get("checks")
        expected_checks = {
            "secret_valid",
            "credential_id_match",
            "merchant_match",
            "subject_match",
            "audience_match",
            "environment_match",
            "lifecycle_valid",
            "scope_valid",
        }
        if (
            not isinstance(checks, dict)
            or set(checks) != expected_checks
            or any(not isinstance(checks[key], bool) for key in expected_checks)
        ):
            raise AttestationClientError("ATTESTATION_RESPONSE_INVALID")

        # Secret-free result only; request body/header material is never returned.
        return {
            "schema": payload["schema"],
            "grant_id": payload["grant_id"],
            "full_binding": payload["full_binding"],
            "checks": {key: checks[key] for key in sorted(expected_checks)},
        }
