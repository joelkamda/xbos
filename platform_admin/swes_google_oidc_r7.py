"""Google OIDC authorization-code + PKCE verifier, SWES Austin TEST ONLY.

No first-admin grant occurs here. Claims must be independently owner-bound
before canonical PC5 commands may establish membership/session/permissions.
Not wired to startup; deployment and external OAuth registration remain held.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode

import httpx
from jose import jwt

TENANT_ID = 910001
ISSUER = "https://accounts.google.com"
AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
CLIENT_RE = re.compile(r"^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
STATE_RE = re.compile(r"^[A-Za-z0-9_-]{32,150}$")
SUB_RE = re.compile(r"^[!-~]{1,255}$")


class OIDCHold(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OIDCConfig:
    client_id: str
    client_secret: str
    callback_url: str
    owner_subject_sha256: str | None = None

    def __post_init__(self):
        if not CLIENT_RE.fullmatch(self.client_id):
            raise OIDCHold("HOLD_OIDC_CLIENT_UNREGISTERED")
        if not isinstance(self.client_secret, str) or len(self.client_secret) < 8:
            raise OIDCHold("HOLD_OIDC_CLIENT_SECRET_ABSENT")
        if (
            self.callback_url !=
            "https://wnd-xafpay-demo-austin-backend.onrender.com/internal/swes/pa/oidc/callback"
        ):
            raise OIDCHold("HOLD_WRONG_CALLBACK")
        if self.owner_subject_sha256 is not None and not SHA_RE.fullmatch(self.owner_subject_sha256):
            raise OIDCHold("HOLD_OWNER_SUBJECT_PIN_INVALID")


@dataclass(frozen=True)
class Challenge:
    state_digest: str
    nonce_digest: str
    code_verifier: str  # server-side ONLY, store sealed; never log or transmit to browser
    created_at: datetime
    expires_at: datetime
    tenant_id: int = TENANT_ID


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject_sha256: str
    audience: str
    authenticated_at: datetime
    assertion_digest: str
    tenant_id: int
    assurance_level: int = 1  # NEVER promote Google sign-in to MFA/step-up


class DurableChallengeStore(Protocol):
    def issue(self, challenge: Challenge) -> None: ...
    def consume(self, state_digest: str) -> Challenge | None: ...
    # consume MUST be atomic, persisted and single-use before external token request


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def subject_digest(sub: str) -> str:
    return digest(ISSUER + "|" + sub)


def begin(config: OIDCConfig, store: DurableChallengeStore, *, now: datetime):
    if now.tzinfo is None:
        raise OIDCHold("HOLD_CLOCK")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    pkce = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    store.issue(Challenge(digest(state), digest(nonce), verifier, now, now + timedelta(minutes=5)))
    query = urlencode({
        "client_id": config.client_id, "redirect_uri": config.callback_url,
        "response_type": "code", "scope": "openid email",
        "state": state, "nonce": nonce,
        "code_challenge": pkce, "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    # 'state' MUST additionally be bound to an HttpOnly Secure SameSite=Lax browser
    # cookie by the actual HTTP adapter. Never expose nonce or verifier to caller.
    return AUTHORIZE + "?" + query, state


def _verified_google_claims(token: str, config: OIDCConfig, *, nonce_digest: str,
                            now: datetime, keys: dict) -> dict:
    if not isinstance(token, str) or len(token) > 16384:
        raise OIDCHold("HOLD_INVALID_ID_TOKEN")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OIDCHold("HOLD_UNTRUSTED_JWT_ALGORITHM")
        if keys.get("keys") is None or not isinstance(keys["keys"], list):
            raise OIDCHold("HOLD_UNTRUSTED_JWKS")
        matches = [
            k for k in keys["keys"] if k.get("kid") == header["kid"]
            and k.get("kty") == "RSA"
            and k.get("use", "sig") == "sig"
            and k.get("alg", "RS256") == "RS256"
        ]
        if len(matches) != 1:
            raise OIDCHold("HOLD_UNTRUSTED_KEY_ID")
        claims = jwt.decode(
            token, matches[0], algorithms=["RS256"], audience=config.client_id,
            options={"verify_iss": False, "verify_exp": True, "verify_aud": True},
        )
    except OIDCHold:
        raise
    except Exception as exc:
        raise OIDCHold("HOLD_INVALID_GOOGLE_SIGNATURE_OR_CLAIMS") from exc
    if claims.get("iss") not in (ISSUER, "accounts.google.com"):
        raise OIDCHold("HOLD_ISSUER_MISMATCH")
    if claims.get("azp") is not None and claims["azp"] != config.client_id:
        raise OIDCHold("HOLD_AUTHORIZED_PARTY_MISMATCH")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not SUB_RE.fullmatch(sub):
        raise OIDCHold("HOLD_SUBJECT_INVALID")
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(digest(nonce), nonce_digest):
        raise OIDCHold("HOLD_NONCE_MISMATCH")
    when = int(now.timestamp())
    try:
        iat, exp = claims["iat"], claims["exp"]
        if type(iat) is not int or type(exp) is not int:
            raise ValueError("time type")
    except (KeyError, ValueError, TypeError) as exc:
        raise OIDCHold("HOLD_TOKEN_CLOCK") from exc
    if iat > when + 30 or iat < when - 300 or exp <= when or exp - iat > 7200:
        raise OIDCHold("HOLD_TOKEN_CLOCK")
    return claims


def finish(config: OIDCConfig, store: DurableChallengeStore, *,
           state: str, browser_state: str, code: str, now: datetime,
           http: httpx.Client) -> VerifiedIdentity:
    if now.tzinfo is None or not isinstance(state, str) or not STATE_RE.fullmatch(state):
        raise OIDCHold("HOLD_STATE_INVALID")
    if not isinstance(browser_state, str) or not hmac.compare_digest(state, browser_state):
        raise OIDCHold("HOLD_BROWSER_STATE_MISMATCH")
    if not isinstance(code, str) or not (8 <= len(code) <= 4096):
        raise OIDCHold("HOLD_CODE_INVALID")
    challenge = store.consume(digest(state))  # atomic DB consume before contacting Google
    if (challenge is None or challenge.tenant_id != TENANT_ID
        or challenge.state_digest != digest(state)
        or challenge.expires_at <= now or challenge.created_at > now
        or now - challenge.created_at > timedelta(minutes=5)):
        raise OIDCHold("HOLD_STATE_EXPIRED_USED_OR_WRONG_TENANT")
    try:
        response = http.post(TOKEN_URL, data={
            "code": code, "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.callback_url,
            "grant_type": "authorization_code",
            "code_verifier": challenge.code_verifier,
        }, timeout=8, follow_redirects=False)
        response.raise_for_status()
        tokens = response.json()
        id_token = tokens["id_token"]
        metadata = http.get(JWKS_URL, timeout=8, follow_redirects=False)
        metadata.raise_for_status()
        keys = metadata.json()
    except Exception as exc:
        # Do not echo secrets, tokens, URLs or provider error bodies.
        raise OIDCHold("HOLD_GOOGLE_EXCHANGE_OR_JWKS_UNAVAILABLE") from exc
    claims = _verified_google_claims(
        id_token, config, nonce_digest=challenge.nonce_digest, now=now, keys=keys
    )
    return VerifiedIdentity(
        ISSUER, subject_digest(claims["sub"]), config.client_id,
        datetime.fromtimestamp(claims["iat"], timezone.utc),
        digest(id_token), TENANT_ID,
    )


def owner_binding_gate(identity: VerifiedIdentity, config: OIDCConfig,
                       *, ceo_approval_registered: bool) -> None:
    # This is necessary but not sufficient for PC5. Approver is an independent
    # authorization authority and must bind actual verified subject fingerprint.
    if (identity.tenant_id != TENANT_ID or identity.issuer != ISSUER
        or identity.audience != config.client_id
        or not ceo_approval_registered or config.owner_subject_sha256 is None
        or not hmac.compare_digest(identity.subject_sha256, config.owner_subject_sha256)):
        raise OIDCHold("HOLD_INDEPENDENT_CEO_OWNER_BINDING_ABSENT")
    # Explicitly do not return a role, PC5 session or 'permission granted'.
