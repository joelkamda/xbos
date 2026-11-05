"""Default-off TEST protected WND launcher, synthetic in-memory key acceptance."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from restaurant.customer_channel import swes_r48_protected_launcher as m


@pytest.fixture(scope="module")
def private_keys():
    return (
        ed25519.Ed25519PrivateKey.generate(),
        ed25519.Ed25519PrivateKey.generate(),
        rsa.generate_private_key(public_exponent=65537, key_size=3072),
    )


def pub_pem(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def env(**overrides):
    params = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": m._WND_SERVICE,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": m._WND_HOST,
        "RENDER_GIT_BRANCH": m._WND_BRANCH,
        "RENDER_GIT_COMMIT": "a" * 40,
        m.ENABLE: "1",
        m.CHECKOUT_ENABLE: "1",
    }
    params.update(overrides)
    return params


def provision(tmp_path, keys, *, changes=None, signed_by=None, encrypted_key=None):
    root, gateway, recipient = keys
    now = datetime.now(timezone.utc)
    raw_root = root.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    raw_gateway = gateway.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    payload = {
        "schema": m._SCHEMA,
        "tenant_id": 910001,
        "location_id": 5,
        "wnd_merchant_public_id": m._MERCHANT,
        "gateway_merchant_id": m._GATEWAY_MERCHANT,
        "order_uuid": m._TARGET_ORDER,
        "wnd_source_sha": "a" * 40,
        "gateway_source_sha": m._GATEWAY_SHA,
        "nonce": str(uuid4()),
        "issued_at_utc": (now-timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (now+timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "gateway_signer_sha256": hashlib.sha256(raw_gateway).hexdigest(),
        "wnd_recipient_spki_sha256": hashlib.sha256(
            recipient.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest(),
        "pcr_policy_root_sha256": hashlib.sha256(raw_root).hexdigest(),
        "operator_approval_id": "pcr-v19-r48-authorized-private",
        "audience": "xafpay-gateway-v2",
        "environment": "staging",
    }
    payload.update(changes or {})
    signer = signed_by or root
    signature = signer.sign(m._SIGN_CONTEXT + m._canonical(payload))
    (tmp_path / "r48-wnd-pcr-launch-grant.json").write_text(json.dumps({
        "payload": payload, "signature_b64": b64(signature),
    }))
    (tmp_path / "r48-pcr-approval-root.pub.pem").write_bytes(pub_pem(root))
    (tmp_path / "r48-gateway-signer.pub.pem").write_bytes(pub_pem(gateway))
    password = b"local-synthetic-test-only-passphrase-123"
    (tmp_path / "r48-wnd-recipient-passphrase").write_bytes(password)
    rsa_priv = encrypted_key or recipient
    (tmp_path / "r48-wnd-recipient.encrypted.pem").write_bytes(
        rsa_priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )
    )
    os.chmod(tmp_path / "r48-wnd-recipient-passphrase", 0o600)
    os.chmod(tmp_path / "r48-wnd-recipient.encrypted.pem", 0o600)
    return env(**{m.ROOT_PIN: hashlib.sha256(raw_root).hexdigest()})


def test_default_off_does_not_read_or_load_any_keys():
    assert m.load_verified_gateway_custody_admission(environ={}) is None
    assert m.load_verified_gateway_custody_admission(environ={m.ENABLE: "0"}) is None


def test_flag_without_real_pcr_grant_denied(tmp_path):
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(
            environ=env(**{m.ROOT_PIN: "a" * 64}),
            secrets_directory=tmp_path,
        )


def test_valid_synthetic_owner_grant_binds_both_real_key_types(tmp_path, private_keys):
    e = provision(tmp_path, private_keys)
    admission = m.load_verified_gateway_custody_admission(
        environ=e, secrets_directory=tmp_path,
    )
    assert admission is not None
    assert admission.signer_public_sha256 == (
        json.loads((tmp_path/"r48-wnd-pcr-launch-grant.json").read_text())
        ["payload"]["gateway_signer_sha256"]
    )
    assert admission.gateway_source_sha == m._GATEWAY_SHA
    assert admission.wnd_source_sha == e["RENDER_GIT_COMMIT"]
    admission.validate()
    assert "PRIVATE KEY" not in repr(admission.signer_public_sha256)


@pytest.mark.parametrize("mutate", [
    {"tenant_id": 2},
    {"location_id": 1},
    {"order_uuid": str(uuid4())},
    {"gateway_merchant_id": "mch_bad"},
    {"gateway_source_sha": "b" * 40},
    {"wnd_source_sha": "f" * 40},
    {"audience": "different-audience"},
    {"environment": "production"},
    {"gateway_signer_sha256": "0" * 64},
    {"wnd_recipient_spki_sha256": "0" * 64},
    {"nonce": str(uuid4()), "expires_at_utc": "2001-01-01T00:00:00Z"},
])
def test_scope_and_key_mutations_fail_closed(tmp_path, private_keys, mutate):
    # Signed by a synthetically valid root but wrong exact operative scope.
    e = provision(tmp_path, private_keys, changes=mutate)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_root_fingerprint_mismatch_refused(tmp_path, private_keys):
    e = provision(tmp_path, private_keys)
    e[m.ROOT_PIN] = "f" * 64
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_wrong_pcr_signer_not_admitted(tmp_path, private_keys):
    rogue = ed25519.Ed25519PrivateKey.generate()
    e = provision(tmp_path, private_keys, signed_by=rogue)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_protected_rsa_substitution_denied(tmp_path, private_keys):
    forged = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    e = provision(tmp_path, private_keys, encrypted_key=forged)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX 0600 enforced on hosted Linux; NTFS ACLs are different")
def test_unprotected_private_key_mode_refused(tmp_path, private_keys):
    e = provision(tmp_path, private_keys)
    path = tmp_path / "r48-wnd-recipient.encrypted.pem"
    os.chmod(path, 0o644)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


@pytest.mark.parametrize("alter", [
    {m.CHECKOUT_ENABLE: "0"},
    {"RENDER_SERVICE_ID": "srv-unauthorized"},
    {"RENDER_GIT_COMMIT": "b" * 40},
    {"RENDER_GIT_BRANCH": "main"},
    {"RENDER_SERVICE_TYPE": "worker"},
])
def test_wrong_live_context_never_accepted(tmp_path, private_keys, alter):
    e = provision(tmp_path, private_keys)
    e.update(alter)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_duplicate_grant_fields_rejected(tmp_path, private_keys):
    e = provision(tmp_path, private_keys)
    path = tmp_path / "r48-wnd-pcr-launch-grant.json"
    data = path.read_text()
    path.write_text(data.replace('"signature_b64":', '"payload": {}, "signature_b64":'))
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_expired_grant_refused(tmp_path, private_keys):
    now = datetime.now(timezone.utc)
    changes = {
        "issued_at_utc": (now-timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (now-timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
    }
    e = provision(tmp_path, private_keys, changes=changes)
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)


def test_no_self_authorization_via_env_only(tmp_path):
    e = env(**{m.ROOT_PIN: "f" * 64})
    # Source SHA and enable flags alone are deliberately insufficient.
    with pytest.raises(m.ProtectedLaunchDenied):
        m.load_verified_gateway_custody_admission(environ=e, secrets_directory=tmp_path)
