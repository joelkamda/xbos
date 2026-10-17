"""Source-only WND credential-binding attestation contract.

The runtime dependency is default-deny.  Tests may inject ephemeral Ed25519 keys,
a mock credential provider, and a mock transport.  This module never reads a
database, a real key file, a real credential store, or the payment path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

from .attestation_client import AttestationClientError, GuardedAttestationClient

ATTESTATION_PERMISSION = "xafpay.attestation.execute"
ATTESTATION_PURPOSE = "wnd.credential-binding.attest.v1"
ATTESTATION_SCHEMA = "xafpay.wnd.credential-binding-attestation.v1"
PCR_EXECUTION_GRANT_SCHEMA = (
    "xafpay.wnd.credential-binding-attestation-execution-grant.v1"
)
GATEWAY_AUDIENCE = "xafpay-gateway-v2"
GATEWAY_PATH = "/internal/wnd-credential-attestations/v1/redeem"
GATEWAY_METHOD = "POST"
GATEWAY_ENVIRONMENT = "STAGING"
REQUIRED_CREDENTIAL_SCOPE = "checkout:create"
REQUEST_LIFETIME_SECONDS = 30
REQUEST_MAX_LIFETIME_SECONDS = 60
REQUEST_FUTURE_SKEW_SECONDS = 5
GRANT_MAX_LIFETIME_SECONDS = 300

WND_ATTESTATION_TARGET = MappingProxyType(
    {
        "credential_id": "8af0fbaf-024b-4ab8-9f99-117a74e952c7",
        "merchant_id": "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c",
        "subject": "xbos",
        "audience": GATEWAY_AUDIENCE,
        "environment": GATEWAY_ENVIRONMENT,
        "required_scope": REQUIRED_CREDENTIAL_SCOPE,
    }
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MOCKABLE_CREDENTIAL_RE = re.compile(
    r"^xps_staging_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"
)


class AttestationDenied(RuntimeError):
    def __init__(self, code: str, status_code: int = 403):
        super().__init__(code)
        self.code = code
        self.status_code = int(status_code)


def _assert_unicode_scalar(value: str) -> None:
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise AttestationDenied("ATTESTATION_CANONICALIZATION_INVALID", 400)


def _utf16_sort_key(value: str) -> bytes:
    _assert_unicode_scalar(value)
    return value.encode("utf-16-be")


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):
        raise AttestationDenied("ATTESTATION_CANONICALIZATION_INVALID", 400)
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise AttestationDenied("ATTESTATION_CANONICALIZATION_INVALID", 400)
    if value == 0:
        return "0"

    raw = repr(float(value)).lower()
    absolute = abs(value)

    # ECMAScript JSON.stringify uses fixed notation in [1e-6, 1e21).
    if 1e-6 <= absolute < 1e21:
        fixed = format(Decimal(raw), "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed or "0"

    if "e" in raw:
        mantissa, exponent = raw.split("e", 1)
        exponent_value = int(exponent)
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        sign = "+" if exponent_value >= 0 else ""
        return f"{mantissa}e{sign}{exponent_value}"

    # Very small/large values normally arrive from repr in scientific notation.
    # Fall back to Decimal scientific form while preserving the shortest repr digits.
    decimal_value = Decimal(raw).normalize()
    digits = "".join(str(digit) for digit in decimal_value.as_tuple().digits)
    sign_prefix = "-" if decimal_value.is_signed() else ""
    exponent = decimal_value.adjusted()
    mantissa = digits[0]
    if len(digits) > 1:
        mantissa += "." + digits[1:].rstrip("0")
        mantissa = mantissa.rstrip(".")
    exp_sign = "+" if exponent >= 0 else ""
    return f"{sign_prefix}{mantissa}e{exp_sign}{exponent}"


def _canonical_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        _assert_unicode_scalar(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _canonical_number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_value(item) for item in value) + "]"
    if isinstance(value, Mapping):
        items: list[str] = []
        for key in sorted(value.keys(), key=lambda item: _utf16_sort_key(str(item))):
            if not isinstance(key, str):
                raise AttestationDenied("ATTESTATION_CANONICALIZATION_INVALID", 400)
            items.append(
                json.dumps(key, ensure_ascii=False, separators=(",", ":"))
                + ":"
                + _canonical_value(value[key])
            )
        return "{" + ",".join(items) + "}"
    raise AttestationDenied("ATTESTATION_CANONICALIZATION_INVALID", 400)


def canonical_attestation_json(value: Any) -> bytes:
    """Gateway-compatible RFC8785/JCS subset for plain JSON values."""
    return _canonical_value(value).encode("utf-8")


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(value)).decode("ascii").rstrip("=")


def decode_canonical_base64url(value: str, expected_size: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AttestationDenied("ATTESTATION_ENCODING_INVALID", 400)
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise AttestationDenied("ATTESTATION_ENCODING_INVALID", 400) from exc
    if len(decoded) != expected_size or base64url_encode(decoded) != value:
        raise AttestationDenied("ATTESTATION_ENCODING_INVALID", 400)
    return decoded


def verify_ed25519_signature(
    message: Any,
    detached_signature: str,
    public_key_raw: bytes,
) -> bool:
    if len(bytes(public_key_raw)) != 32:
        return False
    try:
        signature = decode_canonical_base64url(detached_signature, 64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        key = Ed25519PublicKey.from_public_bytes(bytes(public_key_raw))
        key.verify(signature, canonical_attestation_json(message))
        return True
    except Exception:
        # Verification is a boolean boundary; malformed encodings, unknown
        # keys and invalid signatures all fail closed without an oracle.
        return False


def sign_ed25519_for_test(message: Any, private_key: Any) -> str:
    """Test-vector helper; callers supply an in-memory ephemeral key."""
    try:
        signature = private_key.sign(canonical_attestation_json(message))
    except Exception as exc:
        raise AttestationDenied("ATTESTATION_TEST_SIGNING_FAILED", 500) from exc
    return base64url_encode(signature)


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], code: str) -> None:
    if set(value) != set(expected):
        raise AttestationDenied(code, 403)


def _parse_time(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise AttestationDenied(code, 403)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttestationDenied(code, 403) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttestationDenied(code, 403)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _uuid_text(value: Any, code: str) -> str:
    text = str(value)
    if not _UUID_RE.fullmatch(text):
        raise AttestationDenied(code, 403)
    try:
        UUID(text)
    except ValueError as exc:
        raise AttestationDenied(code, 403) from exc
    return text.lower()


@dataclass(frozen=True)
class OperatorContext:
    user_id: int
    tenant_id: int
    branch_id: int
    role: str
    permissions: frozenset[str]
    expires_at: datetime

    def assert_authorized(self, now: datetime) -> None:
        if (
            self.user_id <= 0
            or self.tenant_id <= 0
            or self.branch_id <= 0
            or not self.role
        ):
            raise AttestationDenied("ATTESTATION_OPERATOR_MISSING", 401)
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise AttestationDenied("ATTESTATION_OPERATOR_EXPIRED", 401)
        if self.expires_at <= now:
            raise AttestationDenied("ATTESTATION_OPERATOR_EXPIRED", 401)
        # Exact permission is mandatory. '*' alone never satisfies this route.
        if ATTESTATION_PERMISSION not in self.permissions:
            raise AttestationDenied("ATTESTATION_PERMISSION_REQUIRED", 403)


@dataclass(frozen=True)
class PcrExecutionGrant:
    schema: str
    issuer_key_id: str
    issuer_reference: str
    grant_id: str
    gateway_grant_id: str
    purpose: str
    tenant_id: int
    branch_id: int
    operator_id: int
    workload_reference: str
    workload_key_id: str
    target: Mapping[str, str]
    issued_at: str
    expires_at: str

    @classmethod
    def parse(cls, value: Any) -> "PcrExecutionGrant":
        if not isinstance(value, Mapping):
            raise AttestationDenied("ATTESTATION_PCR_GRANT_MISSING", 403)
        expected = frozenset(
            {
                "schema",
                "issuer_key_id",
                "issuer_reference",
                "grant_id",
                "gateway_grant_id",
                "purpose",
                "tenant_id",
                "branch_id",
                "operator_id",
                "workload_reference",
                "workload_key_id",
                "target",
                "issued_at",
                "expires_at",
            }
        )
        _exact_keys(value, expected, "ATTESTATION_PCR_GRANT_SHAPE_INVALID")
        target = value.get("target")
        if not isinstance(target, Mapping):
            raise AttestationDenied("ATTESTATION_PCR_GRANT_TARGET_INVALID", 403)
        try:
            tenant_id = int(value["tenant_id"])
            branch_id = int(value["branch_id"])
            operator_id = int(value["operator_id"])
        except (TypeError, ValueError) as exc:
            raise AttestationDenied("ATTESTATION_PCR_GRANT_SCOPE_INVALID", 403) from exc
        return cls(
            schema=str(value["schema"]),
            issuer_key_id=str(value["issuer_key_id"]),
            issuer_reference=str(value["issuer_reference"]),
            grant_id=_uuid_text(value["grant_id"], "ATTESTATION_PCR_GRANT_ID_INVALID"),
            gateway_grant_id=_uuid_text(
                value["gateway_grant_id"],
                "ATTESTATION_GATEWAY_GRANT_ID_INVALID",
            ),
            purpose=str(value["purpose"]),
            tenant_id=tenant_id,
            branch_id=branch_id,
            operator_id=operator_id,
            workload_reference=str(value["workload_reference"]),
            workload_key_id=str(value["workload_key_id"]),
            target={str(key): str(item) for key, item in target.items()},
            issued_at=str(value["issued_at"]),
            expires_at=str(value["expires_at"]),
        )

    def as_signed_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "issuer_key_id": self.issuer_key_id,
            "issuer_reference": self.issuer_reference,
            "grant_id": self.grant_id,
            "gateway_grant_id": self.gateway_grant_id,
            "purpose": self.purpose,
            "tenant_id": self.tenant_id,
            "branch_id": self.branch_id,
            "operator_id": self.operator_id,
            "workload_reference": self.workload_reference,
            "workload_key_id": self.workload_key_id,
            "target": dict(self.target),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


class PcrGrantVerifier:
    def __init__(
        self,
        *,
        issuer_public_keys: Mapping[str, bytes],
        expected_issuer_reference: str,
        expected_workload_reference: str,
        revoked_grant_ids: frozenset[str] = frozenset(),
    ):
        self._issuer_public_keys = {
            str(key): bytes(value) for key, value in issuer_public_keys.items()
        }
        self._expected_issuer_reference = str(expected_issuer_reference)
        self._expected_workload_reference = str(expected_workload_reference)
        self._revoked_grant_ids = frozenset(str(value).lower() for value in revoked_grant_ids)

    def verify(
        self,
        *,
        grant_value: Any,
        signature: str,
        now: datetime,
    ) -> PcrExecutionGrant:
        grant = PcrExecutionGrant.parse(grant_value)

        if grant.schema != PCR_EXECUTION_GRANT_SCHEMA:
            raise AttestationDenied("ATTESTATION_PCR_GRANT_SCHEMA_INVALID", 403)
        if grant.purpose != ATTESTATION_PURPOSE:
            raise AttestationDenied("ATTESTATION_PCR_GRANT_PURPOSE_INVALID", 403)
        if grant.issuer_reference != self._expected_issuer_reference:
            raise AttestationDenied("ATTESTATION_PCR_ISSUER_INVALID", 403)
        if grant.workload_reference != self._expected_workload_reference:
            raise AttestationDenied("ATTESTATION_WND_WORKLOAD_INVALID", 403)
        if not _KEY_ID_RE.fullmatch(grant.issuer_key_id):
            raise AttestationDenied("ATTESTATION_PCR_KEY_ID_INVALID", 403)
        if not _KEY_ID_RE.fullmatch(grant.workload_key_id):
            raise AttestationDenied("ATTESTATION_WORKLOAD_KEY_ID_INVALID", 403)
        if grant.grant_id in self._revoked_grant_ids:
            raise AttestationDenied("ATTESTATION_PCR_GRANT_REVOKED", 403)
        if dict(grant.target) != dict(WND_ATTESTATION_TARGET):
            raise AttestationDenied("ATTESTATION_PCR_GRANT_TARGET_MISMATCH", 403)

        issued_at = _parse_time(grant.issued_at, "ATTESTATION_PCR_GRANT_TIME_INVALID")
        expires_at = _parse_time(grant.expires_at, "ATTESTATION_PCR_GRANT_TIME_INVALID")
        if (
            issued_at > now + timedelta(seconds=REQUEST_FUTURE_SKEW_SECONDS)
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > timedelta(seconds=GRANT_MAX_LIFETIME_SECONDS)
        ):
            raise AttestationDenied("ATTESTATION_PCR_GRANT_EXPIRED", 403)

        public_key = self._issuer_public_keys.get(grant.issuer_key_id)
        if public_key is None:
            raise AttestationDenied("ATTESTATION_PCR_KEY_UNKNOWN", 403)
        if not verify_ed25519_signature(
            grant.as_signed_mapping(),
            signature,
            public_key,
        ):
            raise AttestationDenied("ATTESTATION_PCR_SIGNATURE_INVALID", 403)

        return grant


class WorkloadSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    def sign(self, message: Mapping[str, Any]) -> str: ...


class Ed25519WorkloadSigner:
    """Signer wrapper for injected in-memory/test keys; no key loading occurs here."""

    def __init__(self, *, key_id: str, private_key: Any):
        if not _KEY_ID_RE.fullmatch(str(key_id)):
            raise AttestationDenied("ATTESTATION_WORKLOAD_KEY_ID_INVALID", 500)
        if not hasattr(private_key, "sign"):
            raise AttestationDenied("ATTESTATION_WORKLOAD_KEY_INVALID", 500)
        self._key_id = str(key_id)
        self._private_key = private_key

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, message: Mapping[str, Any]) -> str:
        return sign_ed25519_for_test(message, self._private_key)


class CredentialProvider(Protocol):
    def get_credential(self, *, credential_id: str, environment: str) -> str: ...


class ReplayGuard:
    """In-memory request-id reservation used by source-only/mock qualification."""

    def __init__(self):
        self._reserved: dict[str, datetime] = {}

    def reserve(self, request_id: str, expires_at: datetime, now: datetime) -> None:
        self._reserved = {
            key: expiry
            for key, expiry in self._reserved.items()
            if expiry > now
        }
        if request_id in self._reserved:
            raise AttestationDenied("ATTESTATION_REQUEST_REPLAYED", 409)
        self._reserved[request_id] = expires_at


def validate_workload_envelope(
    envelope: Mapping[str, Any],
    *,
    body: bytes,
    expected_workload_key_id: str,
    now: datetime,
) -> None:
    expected_keys = frozenset(
        {
            "schema",
            "http_method",
            "exact_path",
            "gateway_audience",
            "grant_id",
            "purpose",
            "request_id",
            "issued_at",
            "expires_at",
            "target",
            "body_sha256",
            "workload_key_id",
        }
    )
    _exact_keys(envelope, expected_keys, "ATTESTATION_ENVELOPE_SHAPE_INVALID")
    if (
        envelope.get("schema") != ATTESTATION_SCHEMA
        or envelope.get("http_method") != GATEWAY_METHOD
        or envelope.get("exact_path") != GATEWAY_PATH
        or envelope.get("gateway_audience") != GATEWAY_AUDIENCE
        or envelope.get("purpose") != ATTESTATION_PURPOSE
        or dict(envelope.get("target") or {}) != dict(WND_ATTESTATION_TARGET)
        or envelope.get("workload_key_id") != expected_workload_key_id
    ):
        raise AttestationDenied("ATTESTATION_ENVELOPE_TARGET_INVALID", 403)

    request_id = _uuid_text(
        envelope.get("request_id"),
        "ATTESTATION_REQUEST_ID_INVALID",
    )
    if request_id != str(envelope.get("request_id")).lower():
        raise AttestationDenied("ATTESTATION_REQUEST_ID_INVALID", 403)

    issued_at = _parse_time(envelope.get("issued_at"), "ATTESTATION_TIMESTAMP_INVALID")
    expires_at = _parse_time(envelope.get("expires_at"), "ATTESTATION_TIMESTAMP_INVALID")
    if (
        issued_at > now + timedelta(seconds=REQUEST_FUTURE_SKEW_SECONDS)
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at
        > timedelta(seconds=REQUEST_MAX_LIFETIME_SECONDS)
    ):
        raise AttestationDenied("ATTESTATION_TIMESTAMP_EXPIRED", 403)

    if envelope.get("body_sha256") != hashlib.sha256(body).hexdigest():
        raise AttestationDenied("ATTESTATION_BODY_DIGEST_MISMATCH", 403)


class WndAttestationService:
    def __init__(
        self,
        *,
        enabled: bool,
        grant_verifier: PcrGrantVerifier | None = None,
        workload_signer: WorkloadSigner | None = None,
        credential_provider: CredentialProvider | None = None,
        client: GuardedAttestationClient | None = None,
        clock: Callable[[], datetime] | None = None,
        request_id_factory: Callable[[], str] | None = None,
        replay_guard: ReplayGuard | None = None,
    ):
        self._enabled = bool(enabled)
        self._grant_verifier = grant_verifier
        self._workload_signer = workload_signer
        self._credential_provider = credential_provider
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._request_id_factory = request_id_factory or (lambda: str(uuid4()))
        self._replay_guard = replay_guard or ReplayGuard()

    @classmethod
    def disabled(cls) -> "WndAttestationService":
        return cls(enabled=False)

    def execute(
        self,
        *,
        operator: OperatorContext,
        grant_value: Any,
        grant_signature: str,
    ) -> dict[str, Any]:
        if not self._enabled:
            raise AttestationDenied("ATTESTATION_FEATURE_DISABLED", 503)

        if (
            self._grant_verifier is None
            or self._workload_signer is None
            or self._credential_provider is None
            or self._client is None
        ):
            raise AttestationDenied("ATTESTATION_TRUST_NOT_ADMITTED", 503)

        now = self._clock().astimezone(timezone.utc)
        operator.assert_authorized(now)

        if grant_value is None or not grant_signature:
            raise AttestationDenied("ATTESTATION_PCR_GRANT_MISSING", 403)

        grant = self._grant_verifier.verify(
            grant_value=grant_value,
            signature=str(grant_signature),
            now=now,
        )

        if (
            grant.tenant_id != operator.tenant_id
            or grant.branch_id != operator.branch_id
            or grant.operator_id != operator.user_id
        ):
            raise AttestationDenied("ATTESTATION_OPERATOR_SCOPE_MISMATCH", 403)
        if grant.workload_key_id != self._workload_signer.key_id:
            raise AttestationDenied("ATTESTATION_WORKLOAD_KEY_MISMATCH", 403)

        target = dict(WND_ATTESTATION_TARGET)
        credential = self._credential_provider.get_credential(
            credential_id=target["credential_id"],
            environment=target["environment"],
        )
        if (
            not isinstance(credential, str)
            or not _MOCKABLE_CREDENTIAL_RE.fullmatch(credential)
        ):
            raise AttestationDenied("ATTESTATION_CREDENTIAL_FORMAT_INVALID", 403)

        body_mapping = {
            "grant_id": grant.gateway_grant_id,
            "credential": credential,
        }
        body = canonical_attestation_json(body_mapping)

        request_id = _uuid_text(
            self._request_id_factory(),
            "ATTESTATION_REQUEST_ID_INVALID",
        )
        issued_at = now.replace(microsecond=0)
        expires_at = issued_at + timedelta(seconds=REQUEST_LIFETIME_SECONDS)

        envelope: dict[str, Any] = {
            "schema": ATTESTATION_SCHEMA,
            "http_method": GATEWAY_METHOD,
            "exact_path": GATEWAY_PATH,
            "gateway_audience": GATEWAY_AUDIENCE,
            "grant_id": grant.gateway_grant_id,
            "purpose": ATTESTATION_PURPOSE,
            "request_id": request_id,
            "issued_at": _format_time(issued_at),
            "expires_at": _format_time(expires_at),
            "target": target,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "workload_key_id": self._workload_signer.key_id,
        }

        validate_workload_envelope(
            envelope,
            body=body,
            expected_workload_key_id=self._workload_signer.key_id,
            now=now,
        )

        # Reserve before transport. A timeout/failure never makes this request replayable.
        self._replay_guard.reserve(request_id, expires_at, now)

        canonical_envelope = canonical_attestation_json(envelope)
        workload_signature = self._workload_signer.sign(envelope)

        try:
            result = self._client.redeem(
                body=body,
                workload_envelope=base64url_encode(canonical_envelope),
                workload_signature=workload_signature,
                grant_id=grant.gateway_grant_id,
            )
        except AttestationClientError as exc:
            raise AttestationDenied(exc.code, 502) from exc

        if result.get("full_binding") is not True:
            raise AttestationDenied("ATTESTATION_BINDING_FAILED", 403)

        # Only safe, secret-free evidence crosses back to the operator.
        return {
            "schema": result["schema"],
            "grant_id": result["grant_id"],
            "full_binding": True,
            "checks": dict(result["checks"]),
            "purpose": ATTESTATION_PURPOSE,
            "tenant_id": operator.tenant_id,
            "branch_id": operator.branch_id,
            "operator_id": operator.user_id,
            "request_id": request_id,
        }
