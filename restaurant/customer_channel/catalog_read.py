from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from core.platform.interaction.sql_repository import IA0RepositoryError

from .adapters import AcceptedAuthorityAdapters
from .auth import authenticate_catalog_reader
from .contracts import (
    CATALOG_CONTEXT_PURPOSE,
    CatalogReadBinding,
    CatalogReadError,
)
from .repository import (
    AbsentCatalogReadBindingRepository,
    CatalogReadBindingRepository,
)


class CatalogReadTransport:
    """Read-only Customer Channel transport over accepted XBOS authorities."""

    def __init__(
        self,
        session=None,
        *,
        adapters: Any | None = None,
        binding_repository: CatalogReadBindingRepository | None = None,
    ):
        self.adapters = adapters or AcceptedAuthorityAdapters(session)
        self.binding_repository = (
            binding_repository or AbsentCatalogReadBindingRepository()
        )

    @staticmethod
    def _authorize(
        *,
        raw_token: str | None,
        principal: str | None,
        scopes: str | None,
        correlation_ref: str,
    ) -> str:
        return authenticate_catalog_reader(
            raw_token,
            principal=principal,
            scopes=scopes,
            correlation_ref=correlation_ref,
        )

    def _context(
        self,
        context_binding_ref: UUID,
        *,
        effective_at: datetime,
        correlation_ref: str,
    ):
        if effective_at.tzinfo is None or effective_at.utcoffset() is None:
            raise CatalogReadError(
                "CATALOG_REQUEST_INVALID", correlation_ref=correlation_ref
            )
        try:
            binding = self.adapters.interaction.context_binding_by_public_id(
                context_binding_ref
            )
        except IA0RepositoryError as exc:
            raise CatalogReadError(
                "CATALOG_CONTEXT_REQUIRED", correlation_ref=correlation_ref
            ) from exc
        if (
            binding is None
            or binding.purpose_code != CATALOG_CONTEXT_PURPOSE
            or binding.effective_from > effective_at
            or binding.ended_at is not None
            or (
                binding.expires_at is not None
                and effective_at >= binding.expires_at
            )
        ):
            raise CatalogReadError(
                "CATALOG_CONTEXT_REQUIRED", correlation_ref=correlation_ref
            )
        return binding

    def attest_context(
        self,
        *,
        context_binding_ref: UUID,
        effective_at: datetime,
        raw_token: str | None,
        principal: str | None,
        scopes: str | None,
        correlation_ref: str,
    ) -> dict[str, Any]:
        self._authorize(
            raw_token=raw_token,
            principal=principal,
            scopes=scopes,
            correlation_ref=correlation_ref,
        )
        binding = self._context(
            context_binding_ref,
            effective_at=effective_at,
            correlation_ref=correlation_ref,
        )
        return {
            "context_binding_ref": str(binding.public_id),
            "tenant_id": int(binding.tenant_id),
            "purpose_code": binding.purpose_code,
            "effective_at": effective_at.isoformat(),
            "expires_at": (
                binding.expires_at.isoformat()
                if binding.expires_at is not None
                else None
            ),
        }

    @staticmethod
    def _binding_current(
        binding: CatalogReadBinding,
        *,
        effective_at: datetime,
    ) -> bool:
        return bool(
            binding.enabled
            and binding.effective_from <= effective_at
            and (
                binding.effective_to is None
                or effective_at < binding.effective_to
            )
        )

    def _resolved_binding(
        self,
        *,
        context_binding_ref: UUID,
        merchant_public_id: UUID,
        location_public_id: UUID,
        effective_at: datetime,
        raw_token: str | None,
        principal: str | None,
        scopes: str | None,
        correlation_ref: str,
    ) -> CatalogReadBinding:
        self._authorize(
            raw_token=raw_token,
            principal=principal,
            scopes=scopes,
            correlation_ref=correlation_ref,
        )
        context = self._context(
            context_binding_ref,
            effective_at=effective_at,
            correlation_ref=correlation_ref,
        )
        rows = tuple(
            self.binding_repository.resolve(
                merchant_public_id,
                location_public_id,
                effective_at,
            )
        )
        if not rows:
            raise CatalogReadError(
                "CATALOG_BINDING_MISSING", correlation_ref=correlation_ref
            )
        if len(rows) != 1:
            raise CatalogReadError(
                "CATALOG_BINDING_AMBIGUOUS", correlation_ref=correlation_ref
            )
        binding = rows[0]
        if not self._binding_current(binding, effective_at=effective_at):
            raise CatalogReadError(
                "CATALOG_BINDING_STALE", correlation_ref=correlation_ref
            )
        if (
            binding.tenant_id != context.tenant_id
            or binding.merchant_public_id != merchant_public_id
            or binding.location_public_id != location_public_id
        ):
            raise CatalogReadError(
                "CATALOG_BINDING_MISMATCH", correlation_ref=correlation_ref
            )
        return binding

    @staticmethod
    def _binding_dict(binding: CatalogReadBinding) -> dict[str, Any]:
        return {
            "binding_ref": str(binding.binding_ref),
            "binding_version": int(binding.binding_version),
            "tenant_id": int(binding.tenant_id),
            "catalog_public_id": str(binding.catalog_public_id),
            "price_code": binding.price_code,
            "currency": binding.currency,
            "scope_type": binding.scope_type,
            "scope_id": binding.scope_id,
        }

    def resolve_binding(
        self,
        *,
        context_binding_ref: UUID,
        merchant_public_id: UUID,
        location_public_id: UUID,
        effective_at: datetime,
        raw_token: str | None,
        principal: str | None,
        scopes: str | None,
        correlation_ref: str,
    ) -> dict[str, Any]:
        binding = self._resolved_binding(
            context_binding_ref=context_binding_ref,
            merchant_public_id=merchant_public_id,
            location_public_id=location_public_id,
            effective_at=effective_at,
            raw_token=raw_token,
            principal=principal,
            scopes=scopes,
            correlation_ref=correlation_ref,
        )
        return self._binding_dict(binding)

    def menu(
        self,
        *,
        context_binding_ref: UUID,
        merchant_public_id: UUID,
        location_public_id: UUID,
        binding_ref: UUID,
        binding_version: int,
        effective_at: datetime,
        raw_token: str | None,
        principal: str | None,
        scopes: str | None,
        correlation_ref: str,
    ) -> dict[str, Any]:
        binding = self._resolved_binding(
            context_binding_ref=context_binding_ref,
            merchant_public_id=merchant_public_id,
            location_public_id=location_public_id,
            effective_at=effective_at,
            raw_token=raw_token,
            principal=principal,
            scopes=scopes,
            correlation_ref=correlation_ref,
        )
        if binding.binding_ref != binding_ref:
            raise CatalogReadError(
                "CATALOG_BINDING_MISMATCH", correlation_ref=correlation_ref
            )
        if binding.binding_version != binding_version:
            raise CatalogReadError(
                "CATALOG_BINDING_VERSION_MISMATCH",
                correlation_ref=correlation_ref,
            )
        menu_inputs = (
            binding.tenant_id,
            binding.catalog_public_id,
            effective_at,
            binding.price_code,
            binding.currency,
            binding.scope_type,
            binding.scope_id,
        )
        try:
            projection = self.adapters.r2.menu(*menu_inputs)
        except Exception as exc:
            raise CatalogReadError(
                "CATALOG_SEMANTIC_FAILURE", correlation_ref=correlation_ref
            ) from exc
        return jsonable_encoder(projection)
