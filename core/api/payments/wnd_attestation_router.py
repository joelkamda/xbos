"""Strict WND operator entry for credential-binding attestation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from core.security.jwt_service import JWTService
from core.integrations.xafpay_v2.attestation_service import (
    ATTESTATION_PERMISSION,
    AttestationDenied,
    OperatorContext,
    WndAttestationService,
)

router = APIRouter()

_DISABLED_SERVICE = WndAttestationService.disabled()


class WndAttestationExecutePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant: dict[str, Any]
    grant_signature: str


def get_wnd_attestation_service() -> WndAttestationService:
    # Source-only tranche: no live trust material or transport is admitted.
    return _DISABLED_SERVICE


def _operator_context(request: Request) -> OperatorContext:
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="ATTESTATION_OPERATOR_MISSING")

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="ATTESTATION_OPERATOR_MISSING")
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="ATTESTATION_OPERATOR_MISSING")

    try:
        claims = JWTService().decode_token(token)
        if claims.get("type") != "access":
            raise ValueError("wrong token type")
        user_id = int(claims["sub"])
        tenant_id = int(claims["tenant_id"])
        branch_id = int(claims["branch_id"])
        role = str(claims["role"]).strip()
        exp = int(claims["exp"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="ATTESTATION_OPERATOR_INVALID") from exc

    if (
        user_id != int(user.get("user_id", -1))
        or tenant_id != int(user.get("tenant_id", -1))
        or branch_id != int(user.get("branch_id", -1))
        or role != str(user.get("role", "")).strip()
    ):
        raise HTTPException(status_code=403, detail="ATTESTATION_OPERATOR_CONTEXT_MISMATCH")

    permissions = getattr(request.state, "permissions", user.get("permissions", []))
    if not isinstance(permissions, list):
        permissions = []
    permission_set = frozenset(str(value).strip() for value in permissions if value)
    if ATTESTATION_PERMISSION not in permission_set:
        # Explicit permission only. '*' and superadmin role do not bypass.
        raise HTTPException(status_code=403, detail="ATTESTATION_PERMISSION_REQUIRED")

    return OperatorContext(
        user_id=user_id,
        tenant_id=tenant_id,
        branch_id=branch_id,
        role=role,
        permissions=permission_set,
        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
    )


@router.post("/xafpay/attestation/execute")
async def execute_wnd_attestation(
    payload: WndAttestationExecutePayload,
    request: Request,
    service: WndAttestationService = Depends(get_wnd_attestation_service),
):
    operator = _operator_context(request)
    try:
        return service.execute(
            operator=operator,
            grant_value=payload.grant,
            grant_signature=payload.grant_signature,
        )
    except AttestationDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
