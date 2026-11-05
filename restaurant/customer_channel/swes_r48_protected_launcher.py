"""R48 default-OFF WND launch from independently signed, owner-protected trust.

No operative signer, recipient key, nonce, or RELEASE authority is generated here.
A launch requires a PCR-signed exact-source grant, independent PCR root pin,
protected recipient key and matching Gateway signing public key. Missing evidence
is a startup denial, never an environment-only trust admission.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from .swes_r48_gateway_custody import PinnedGatewayCustodyAdmission, _canonical

ENABLE = "XAFPAY_R48_WND_GATEWAY_CUSTODY_ENABLED"
CHECKOUT_ENABLE = "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED"
ROOT_PIN = "XAFPAY_R48_PCR_POLICY_ROOT_SHA256"
_SCHEMA = "xafpay.pcr.r48.wnd.protected-launch-grant.v1"
_SIGN_CONTEXT = b"xafpay:pcr:r48:wnd:protected-launch-grant:v1\x00"
_GATEWAY_SHA = "109f264a813b8f89c8d26d9ee2b448f1862d6889"
_WND_SERVICE = "srv-db3vej67bikc73ai2080"
_WND_BRANCH = "compat/wnd-demo-cc-r1-legacy-neutral-bridge"
_WND_HOST = "wnd-xafpay-demo-austin-backend.onrender.com"
_TARGET_ORDER = "cba5f76f-73f7-421b-8cce-f8b8823270df"
_MERCHANT = "4b196022-55a1-548c-b122-f1f9e4b78bea"
_GATEWAY_MERCHANT = "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_FIELDS = frozenset({
    "schema", "tenant_id", "location_id", "wnd_merchant_public_id",
    "gateway_merchant_id", "order_uuid", "wnd_source_sha",
    "gateway_source_sha", "nonce", "issued_at_utc", "expires_at_utc",
    "gateway_signer_sha256", "wnd_recipient_spki_sha256",
    "pcr_policy_root_sha256", "operator_approval_id",
    "audience", "environment",
})


class ProtectedLaunchDenied(RuntimeError):
    """Fail closed without disclosing the keys or grant content."""

    def __init__(self):
        super().__init__("R48_WND_PROTECTED_LAUNCH_NOT_ADMITTED")


def _decode_b64(raw: Any, *, length: int) -> bytes:
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ProtectedLaunchDenied()
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ProtectedLaunchDenied() from exc
    if len(data) != length:
        raise ProtectedLaunchDenied()
    return data


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtectedLaunchDenied()
        result[key] = value
    return result


def _read_file(directory: Path, name: str, *, private: bool) -> bytes:
    path = directory / name  # Fixed file names; no caller-supplied path segment.
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16_384:
            raise ProtectedLaunchDenied()
        # Render is Linux and enforces actual owner-only file permission bits.
        # Windows developer tests use synthetic keys; NTFS ACLs do not map to
        # POSIX mode bits and cannot establish hosted operative custody.
        if private and os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ProtectedLaunchDenied()
        return path.read_bytes()
    except (OSError, PermissionError) as exc:
        raise ProtectedLaunchDenied() from exc


def _utc(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise ProtectedLaunchDenied()
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise ProtectedLaunchDenied() from exc
    if dt.utcoffset() != timedelta(0):
        raise ProtectedLaunchDenied()
    return dt


def _public_key(data: bytes, expected_type):
    try:
        key = serialization.load_pem_public_key(data)
    except (ValueError, TypeError) as exc:
        raise ProtectedLaunchDenied() from exc
    if not isinstance(key, expected_type):
        raise ProtectedLaunchDenied()
    return key


def _read_approval(directory: Path) -> dict:
    try:
        signed = json.loads(
            _read_file(directory, "r48-wnd-pcr-launch-grant.json", private=False),
            object_pairs_hook=_unique_pairs,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ProtectedLaunchDenied() from exc
    if not isinstance(signed, dict) or set(signed) != {"payload", "signature_b64"}:
        raise ProtectedLaunchDenied()
    if not isinstance(signed["payload"], dict) or set(signed["payload"]) != _FIELDS:
        raise ProtectedLaunchDenied()
    return signed


def _assert_hosted_context(env: Mapping[str, str]) -> None:
    expected = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": _WND_SERVICE,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": _WND_HOST,
        "RENDER_GIT_BRANCH": _WND_BRANCH,
        CHECKOUT_ENABLE: "1",
    }
    if any(env.get(k) != v for k, v in expected.items()):
        raise ProtectedLaunchDenied()
    if not _GIT_SHA.fullmatch(str(env.get("RENDER_GIT_COMMIT", ""))):
        raise ProtectedLaunchDenied()


def load_verified_gateway_custody_admission(
    *,
    environ: Mapping[str, str],
    secrets_directory: Path | None = None,
    now: datetime | None = None,
) -> PinnedGatewayCustodyAdmission | None:
    """Acquire existing protected owner keys; never generate or self-approve.

    Only a separately signed PCR launch grant can authenticate this launcher.
    In hosted Render, all trust material must be mounted at /etc/secrets.
    Directory override is test-only and must not be supplied by the app caller.
    """
    if environ.get(ENABLE) != "1":
        return None
    try:
        _assert_hosted_context(environ)
        root_pin = environ.get(ROOT_PIN, "")
        if not _SHA256.fullmatch(root_pin):
            raise ProtectedLaunchDenied()
        # Synthetic tests may supply a temporary root only off the actual
        # hosted Linux runtime; the real WND process uses /etc/secrets.
        if (secrets_directory is not None
                and environ.get("RENDER") == "true"
                and os.path.exists("/etc/secrets")):
            raise ProtectedLaunchDenied()
        directory = secrets_directory or Path("/etc/secrets")
        grant = _read_approval(directory)
        payload = grant["payload"]
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() != timedelta(0):
            raise ProtectedLaunchDenied()

        issued = _utc(payload["issued_at_utc"])
        expires = _utc(payload["expires_at_utc"])
        if not (issued <= current < expires <= issued + timedelta(hours=2)):
            raise ProtectedLaunchDenied()
        try:
            nonce = UUID(payload["nonce"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise ProtectedLaunchDenied() from exc
        if nonce.int == 0 or not isinstance(payload["operator_approval_id"], str):
            raise ProtectedLaunchDenied()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", payload["operator_approval_id"]):
            raise ProtectedLaunchDenied()

        requirements = {
            "schema": _SCHEMA,
            "tenant_id": 910001,
            "location_id": 5,
            "wnd_merchant_public_id": _MERCHANT,
            "gateway_merchant_id": _GATEWAY_MERCHANT,
            "order_uuid": _TARGET_ORDER,
            "wnd_source_sha": environ["RENDER_GIT_COMMIT"],
            "gateway_source_sha": _GATEWAY_SHA,
            "pcr_policy_root_sha256": root_pin,
            "audience": "xafpay-gateway-v2",
            "environment": "staging",
        }
        if any(type(payload.get(k)) is not type(v) or payload[k] != v for k, v in requirements.items()):
            raise ProtectedLaunchDenied()

        root_key = _public_key(
            _read_file(directory, "r48-pcr-approval-root.pub.pem", private=False),
            ed25519.Ed25519PublicKey,
        )
        raw_root = root_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        if not hmac.compare_digest(hashlib.sha256(raw_root).hexdigest(), root_pin):
            raise ProtectedLaunchDenied()
        try:
            root_key.verify(
                _decode_b64(grant["signature_b64"], length=64),
                _SIGN_CONTEXT + _canonical(payload),
            )
        except InvalidSignature as exc:
            raise ProtectedLaunchDenied() from exc

        gw_key = _public_key(
            _read_file(directory, "r48-gateway-signer.pub.pem", private=False),
            ed25519.Ed25519PublicKey,
        )
        raw_gateway = gw_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        gateway_fingerprint = hashlib.sha256(raw_gateway).hexdigest()
        if (not isinstance(payload["gateway_signer_sha256"], str)
                or not _SHA256.fullmatch(payload["gateway_signer_sha256"])
                or not hmac.compare_digest(gateway_fingerprint, payload["gateway_signer_sha256"])):
            raise ProtectedLaunchDenied()

        password = _read_file(directory, "r48-wnd-recipient-passphrase", private=True).rstrip(b"\r\n")
        if len(password) < 16 or len(password) > 1024:
            raise ProtectedLaunchDenied()
        pem = _read_file(directory, "r48-wnd-recipient.encrypted.pem", private=True)
        try:
            recipient = serialization.load_pem_private_key(pem, password=password)
        except (TypeError, ValueError) as exc:
            raise ProtectedLaunchDenied() from exc
        if not isinstance(recipient, rsa.RSAPrivateKey) or recipient.key_size < 3072:
            raise ProtectedLaunchDenied()
        spki = recipient.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        recipient_fingerprint = hashlib.sha256(spki).hexdigest()
        if (not isinstance(payload["wnd_recipient_spki_sha256"], str)
                or not _SHA256.fullmatch(payload["wnd_recipient_spki_sha256"])
                or not hmac.compare_digest(recipient_fingerprint, payload["wnd_recipient_spki_sha256"])):
            raise ProtectedLaunchDenied()

        admitted = PinnedGatewayCustodyAdmission(
            signer_public_key=gw_key,
            signer_public_sha256=gateway_fingerprint,
            recipient_private_key=recipient,
            approved_nonce=nonce,
            wnd_source_sha=environ["RENDER_GIT_COMMIT"],
            gateway_source_sha=_GATEWAY_SHA,
            approved_until_utc=expires,
        )
        admitted.validate()
        return admitted
    except ProtectedLaunchDenied:
        raise
    except Exception as exc:
        raise ProtectedLaunchDenied() from exc
