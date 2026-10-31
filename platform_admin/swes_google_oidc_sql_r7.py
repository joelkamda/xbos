"""Durable Google OIDC challenge store, SQLAlchemy/PostgreSQL only.

Requires separately approved additive schema and pre-provisioned Fernet key.
This is NOT a PC5 credential store or an administrator enrollment issuer.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from platform_admin.swes_google_oidc_r7 import TENANT_ID, Challenge, OIDCHold


class SQLChallengeStore:
    def __init__(self, engine: Engine, *, fernet_key: str):
        if not isinstance(fernet_key, str):
            raise OIDCHold("HOLD_CHALLENGE_SEAL_KEY_ABSENT")
        try:
            self._seal = Fernet(fernet_key.encode("ascii"))
        except Exception as exc:
            raise OIDCHold("HOLD_CHALLENGE_SEAL_KEY_INVALID") from exc
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def issue(self, challenge: Challenge) -> None:
        if challenge.tenant_id != TENANT_ID or challenge.created_at.tzinfo is None:
            raise OIDCHold("HOLD_CHALLENGE_SCOPE")
        ciphertext = self._seal.encrypt(challenge.code_verifier.encode("ascii"))
        with self._session_factory.begin() as session:
            if session.execute(text("SELECT current_database()")).scalar_one() != "wnd_xafpay_demo_austin_db":
                raise OIDCHold("HOLD_WRONG_DATABASE")
            session.execute(text("""
                INSERT INTO public.swes_pa_oidc_challenges
                  (state_digest, nonce_digest, verifier_ciphertext, tenant_id, created_at, expires_at)
                VALUES (:state, :nonce, :verifier, :tenant, :created, :expires)
            """), {
                "state":challenge.state_digest, "nonce":challenge.nonce_digest,
                "verifier":ciphertext, "tenant":challenge.tenant_id,
                "created":challenge.created_at, "expires":challenge.expires_at,
            })

    def consume(self, state_digest: str) -> Challenge | None:
        # Commit the DELETE before network IO; same state cannot be redeemed twice
        # even after timeout, worker restart, or concurrent process callback.
        with self._session_factory.begin() as session:
            if session.execute(text("SELECT current_database()")).scalar_one() != "wnd_xafpay_demo_austin_db":
                raise OIDCHold("HOLD_WRONG_DATABASE")
            row = session.execute(text("""
                DELETE FROM public.swes_pa_oidc_challenges
                WHERE state_digest=:state AND tenant_id=:tenant
                RETURNING state_digest,nonce_digest,verifier_ciphertext,
                          tenant_id,created_at,expires_at
            """), {"state":state_digest, "tenant":TENANT_ID}).mappings().first()
        if row is None:
            return None
        try:
            verifier = self._seal.decrypt(bytes(row["verifier_ciphertext"]), ttl=350).decode("ascii")
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise OIDCHold("HOLD_CHALLENGE_SEAL_INVALID_OR_EXPIRED") from exc
        return Challenge(row["state_digest"], row["nonce_digest"], verifier,
                         row["created_at"], row["expires_at"], row["tenant_id"])
