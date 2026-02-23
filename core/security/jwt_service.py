from jose import jwt, JWTError, ExpiredSignatureError
from datetime import datetime, timedelta
from settings import settings


class JWTService:
    """
    XBOS-standard JWT service.

    Supports:
      (i)  RBAC permission injection
      (ii) Legacy (user_id, tenant, branch, role)
      (iii) New-style dict payloads
      (iv) Refresh token rebuilding
    """

    # =========================================================
    # ACCESS TOKEN
    # =========================================================
    def create_access_token(
        self,
        user_or_payload,
        tenant_id: int = None,
        branch_id: int = None,
        role: str = None,
        permissions: list = None,
        expires_minutes: int = 60
    ):
        now = datetime.utcnow()

        # Normalize permissions
        permissions = sorted(list(set(permissions or [])))

        # -----------------------------------------------------
        # MODE A — New XBOS dict payload
        # -----------------------------------------------------
        if isinstance(user_or_payload, dict):
            payload = user_or_payload.copy()

            # Merge permissions if payload already includes some
            existing = payload.get("permissions", [])
            payload["permissions"] = sorted(list(set(existing + permissions)))

            payload["iat"] = now
            payload["exp"] = now + timedelta(minutes=expires_minutes)
            payload.setdefault("type", "access")

            return jwt.encode(
                payload,
                settings.JWT_SECRET,
                algorithm=settings.JWT_ALGORITHM
            )

        # -----------------------------------------------------
        # MODE B — Legacy user_id
        # -----------------------------------------------------
        user_id = user_or_payload

        payload = {
            "sub": str(user_id),
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "role": role,
            "permissions": permissions,
            "iat": now,
            "exp": now + timedelta(minutes=expires_minutes),
            "type": "access",
        }

        return jwt.encode(
            payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )

    # =========================================================
    # REFRESH TOKEN  (NO tenant/branch/role included)
    # =========================================================
    def create_refresh_token(self, user_id: int, expires_days: int = 30):
        now = datetime.utcnow()

        payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(days=expires_days),
            "type": "refresh"
        }

        return jwt.encode(
            payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )

    # =========================================================
    # DECODE ANY TOKEN
    # =========================================================
    def decode_token(self, token: str):
        try:
            return jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except ExpiredSignatureError:
            raise ValueError("Token has expired")
        except JWTError:
            raise ValueError("Token is invalid")

    # =========================================================
    # REBUILD ACCESS TOKEN FROM REFRESH TOKEN
    #
    # NOTE: refresh_payload contains ONLY:
    #   sub
    #   exp
    #   type=refresh
    #
    # Tenant, branch, role MUST be provided by AuthService.refresh()
    # (because refresh token does not carry them)
    # =========================================================
    def refresh_access_token(self, *, user_id: int, tenant_id: int,
                             branch_id: int, role: str, permissions: list):
        """
        Called by AuthService.refresh()

        Recreates a fresh access token, preserving RBAC permissions.
        """
        return self.create_access_token(
            user_or_payload={
                "sub": str(user_id),
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "role": role,
            },
            permissions=permissions,
            expires_minutes=60
        )
