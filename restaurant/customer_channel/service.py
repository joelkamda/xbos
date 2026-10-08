from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from core.platform.interaction.sql_repository import IA0RepositoryError
from restaurant.r1.contracts import ResourceRole

from .adapters import AcceptedAuthorityAdapters
from .auth import authenticate_bearer_value
from .contracts import (
    CONFIRMATION_TTL_SECONDS,
    CONTACT_PURPOSE,
    CONTEXT_PURPOSE,
    DELIVERY_ADDRESS_PURPOSE,
    AuthoritativeLine,
    BoundContact,
    ConfirmationProjection,
    H1BError,
    OrderProjection,
    TrustedCheckoutScope,
    payment_projection_dict,
)
from .delivery_policy import normalized_address, select_delivery_policy


_FORBIDDEN_CONFIRMATION_FIELDS = {
    "tenant_id",
    "organization_unit_id",
    "amount",
    "currency",
    "delivery_fee",
    "total",
}
_ALLOWED_CONFIRMATION_FIELDS = {
    "service_mode",
    "table_ref",
    "contact_ref",
    "delivery_address_ref",
    "cart_lines",
    "observed_quote_ref",
    "observed_quote_version",
}


def _utc(value: datetime | None = None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise H1BError("ORDER_NOT_READY")
    return selected.astimezone(timezone.utc)


def _uuid(value: Any, *, code: str = "ORDER_NOT_READY") -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:
        raise H1BError(code) from exc


def _quantity(value: Any) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise H1BError("ORDER_NOT_READY") from exc
    if not selected.is_finite() or selected <= 0:
        raise H1BError("ORDER_NOT_READY")
    return selected


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _client_submit_ref(value: Any) -> tuple[str, str]:
    selected = str(value or "").strip()
    if not selected or len(selected.encode("utf-8")) > 160:
        raise H1BError("IDEMPOTENCY_CONFLICT")
    digest = hashlib.sha256(selected.encode("utf-8")).hexdigest()
    return selected, digest


def _line_dict(line: AuthoritativeLine) -> dict[str, Any]:
    return {
        "catalog_entry_ref": str(line.catalog_entry_ref),
        "target_type": line.target_type,
        "target_ref": str(line.target_ref),
        "price_ref": str(line.price_ref),
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "currency": line.currency,
        "catalog_entry_version": line.catalog_entry_version,
        "price_version": line.price_version,
        "option_refs": [str(x) for x in line.option_refs],
        "modifier_selections": list(line.modifier_selections),
        "line_kind": line.line_kind,
    }


def _line_from_dict(value: dict[str, Any]) -> AuthoritativeLine:
    return AuthoritativeLine(
        UUID(value["catalog_entry_ref"]),
        str(value["target_type"]),
        UUID(value["target_ref"]),
        UUID(value["price_ref"]),
        Decimal(str(value["quantity"])),
        Decimal(str(value["unit_price"])),
        str(value["currency"]),
        int(value["catalog_entry_version"]),
        int(value["price_version"]),
        tuple(UUID(x) for x in value.get("option_refs", [])),
        tuple(dict(x) for x in value.get("modifier_selections", [])),
        str(value.get("line_kind") or "item"),
    )


class RestaurantCustomerChannelCheckoutAuthority:
    def __init__(self, session):
        self.session = session
        self.adapters = AcceptedAuthorityAdapters(session)
        self.repo = self.adapters.repo

    @staticmethod
    def _binding_current(binding: Any, *, purpose: str, tenant_id: int | None, at: datetime) -> bool:
        return bool(
            binding is not None
            and binding.purpose_code == purpose
            and (tenant_id is None or binding.tenant_id == tenant_id)
            and binding.ended_at is None
            and (binding.expires_at is None or at < binding.expires_at)
        )

    def _binding_by_public_id(
        self,
        public_id: UUID,
        *,
        purpose: str,
        tenant_id: int | None,
        at: datetime,
        correlation_ref: str,
    ):
        try:
            binding = self.adapters.interaction.context_binding_by_public_id(public_id)
        except IA0RepositoryError as exc:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=correlation_ref) from exc
        if not self._binding_current(binding, purpose=purpose, tenant_id=tenant_id, at=at):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=correlation_ref)
        return binding

    def trusted_scope(
        self,
        *,
        bearer_token: str | None,
        context_binding_ref: UUID,
        correlation_ref: str,
        at: datetime | None = None,
    ) -> TrustedCheckoutScope:
        now = _utc(at)
        if not correlation_ref or not str(correlation_ref).strip():
            raise H1BError("CONTEXT_MISMATCH")
        trace = str(correlation_ref).strip()
        rotation_slot = authenticate_bearer_value(bearer_token, correlation_ref=trace)
        binding = self._binding_by_public_id(
            context_binding_ref,
            purpose=CONTEXT_PURPOSE,
            tenant_id=None,
            at=now,
            correlation_ref=trace,
        )
        authorization = self.repo.service_authorization(
            binding.tenant_id,
            at=now,
            rotation_slot=rotation_slot,
        )
        branch_id = self.repo.branch_for_location(binding.tenant_id, authorization.location_id)
        try:
            structure = self.adapters.structure.resolve(
                tenant_id=binding.tenant_id,
                legacy_branch_id=branch_id,
            )
        except Exception as exc:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace) from exc
        if (
            structure.organization_unit is None
            or structure.location is None
            or structure.location.id != authorization.location_id
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=trace)
        merchant = self.repo.operational_merchant(binding.tenant_id)
        return TrustedCheckoutScope(
            binding.tenant_id,
            branch_id,
            structure.organization_unit.id,
            structure.location.id,
            merchant,
            binding.public_id,
            authorization.service_identity_public_id,
            structure.tenant.currency,
            trace,
        )

    def _bound_contact(
        self,
        *,
        scope: TrustedCheckoutScope,
        binding_ref: UUID,
        purpose: str,
        contact_type: str | None,
        at: datetime,
    ) -> BoundContact:
        binding = self._binding_by_public_id(
            binding_ref,
            purpose=purpose,
            tenant_id=scope.tenant_id,
            at=at,
            correlation_ref=scope.correlation_ref,
        )
        if binding.source_reference.authority != "pc2.party_contact":
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        try:
            contact_id = int(binding.source_reference.reference)
        except Exception as exc:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref) from exc
        contact = self.repo.party_contact(scope.tenant_id, contact_id, at=at)
        if contact_type is not None and contact.contact_type != contact_type:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        return replace(contact, binding_public_id=binding.public_id)

    def _table_context(self, scope: TrustedCheckoutScope, table_ref: UUID):
        resource = self.repo.resource(scope.tenant_id, table_ref)
        if (
            resource is None
            or resource.lifecycle_status != "active"
            or int(resource.location_id or 0) != scope.location_id
            or int(resource.organization_unit_id or 0) != scope.organization_unit_id
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        profile = self.adapters.r1_repo.resource_profile(scope.tenant_id, table_ref)
        if (
            profile is None
            or profile.role is not ResourceRole.TABLE
            or "dine_in" not in profile.service_mode_codes
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        return resource, profile

    def _canonical_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise H1BError("ORDER_NOT_READY")
        if _FORBIDDEN_CONFIRMATION_FIELDS.intersection(payload):
            raise H1BError("ORDER_NOT_READY")
        if set(payload) - _ALLOWED_CONFIRMATION_FIELDS:
            raise H1BError("ORDER_NOT_READY")
        mode = str(payload.get("service_mode") or "").strip().lower()
        if mode not in {"dine_in", "takeaway", "delivery"}:
            raise H1BError("UNSUPPORTED_METHOD")
        cart = payload.get("cart_lines")
        if not isinstance(cart, list) or not cart:
            raise H1BError("ORDER_NOT_READY")
        normalized_lines: list[dict[str, Any]] = []
        for line in cart:
            if not isinstance(line, dict) or set(line) - {"catalog_entry_ref", "quantity", "option_refs"}:
                raise H1BError("ORDER_NOT_READY")
            entry = _uuid(line.get("catalog_entry_ref"))
            qty = _quantity(line.get("quantity"))
            raw_options = line.get("option_refs") or []
            if not isinstance(raw_options, list):
                raise H1BError("ORDER_NOT_READY")
            options = tuple(_uuid(x) for x in raw_options)
            normalized_lines.append(
                {
                    "catalog_entry_ref": str(entry),
                    "quantity": str(qty),
                    "option_refs": [str(x) for x in options],
                }
            )
        def optional_ref(name: str) -> str | None:
            value = payload.get(name)
            return str(_uuid(value)) if value is not None else None
        return {
            "service_mode": mode,
            "table_ref": optional_ref("table_ref"),
            "contact_ref": optional_ref("contact_ref"),
            "delivery_address_ref": optional_ref("delivery_address_ref"),
            "cart_lines": normalized_lines,
            "observed_quote_ref": (
                str(payload.get("observed_quote_ref")).strip()
                if payload.get("observed_quote_ref") is not None
                else None
            ),
            "observed_quote_version": (
                str(payload.get("observed_quote_version")).strip()
                if payload.get("observed_quote_version") is not None
                else None
            ),
        }

    def _build_snapshot(
        self,
        *,
        scope: TrustedCheckoutScope,
        request: dict[str, Any],
        at: datetime,
    ) -> tuple[dict[str, Any], tuple[AuthoritativeLine, ...]]:
        mode_code = request["service_mode"]
        try:
            mode = self.adapters.r1.mode(scope.tenant_id, mode_code)
        except Exception as exc:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref) from exc
        if not mode.active:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        table_ref = UUID(request["table_ref"]) if request.get("table_ref") else None
        contact_ref = UUID(request["contact_ref"]) if request.get("contact_ref") else None
        address_ref = (
            UUID(request["delivery_address_ref"])
            if request.get("delivery_address_ref")
            else None
        )
        contact: BoundContact | None = None
        address: BoundContact | None = None

        if mode_code == "dine_in":
            if table_ref is None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            self._table_context(scope, table_ref)
        elif table_ref is not None:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)

        if mode_code == "takeaway":
            if contact_ref is None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            contact = self._bound_contact(
                scope=scope,
                binding_ref=contact_ref,
                purpose=CONTACT_PURPOSE,
                contact_type=None,
                at=at,
            )
        elif mode_code == "delivery":
            if contact_ref is None or address_ref is None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            contact = self._bound_contact(
                scope=scope,
                binding_ref=contact_ref,
                purpose=CONTACT_PURPOSE,
                contact_type=None,
                at=at,
            )
            address = self._bound_contact(
                scope=scope,
                binding_ref=address_ref,
                purpose=DELIVERY_ADDRESS_PURPOSE,
                contact_type="postal_address",
                at=at,
            )
            if address.party_public_id != contact.party_public_id:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        elif contact_ref is not None:
            contact = self._bound_contact(
                scope=scope,
                binding_ref=contact_ref,
                purpose=CONTACT_PURPOSE,
                contact_type=None,
                at=at,
            )

        lines: list[AuthoritativeLine] = []
        for item in request["cart_lines"]:
            line = self.adapters.resolve_item_line(
                scope=scope,
                catalog_entry_ref=UUID(item["catalog_entry_ref"]),
                quantity=Decimal(item["quantity"]),
                option_refs=tuple(UUID(x) for x in item.get("option_refs", [])),
                at=at,
                currency=scope.currency,
            )
            lines.append(line)

        policy_refs: list[str] = []
        if mode_code == "delivery":
            assert address is not None
            policies = self.repo.delivery_policies(
                scope.tenant_id,
                scope.organization_unit_id,
                scope.location_id,
            )
            policy = select_delivery_policy(
                policies,
                address=normalized_address(address.contact_value, address.metadata),
                at=at,
            )
            fee = self.adapters.resolve_fixed_fee_line(
                scope=scope,
                catalog_entry_ref=policy.fee_catalog_entry_public_id,
                price_ref=policy.fee_price_public_id,
                at=at,
                currency=scope.currency,
            )
            policy_refs.append(f"delivery:{policy.public_id}:v{policy.policy_version}")
            if fee.unit_price != Decimal("0"):
                lines.append(fee)

        currencies = {line.currency for line in lines}
        if currencies != {scope.currency}:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        total = sum((line.total for line in lines), Decimal("0"))
        snapshot = {
            "schema": "xbos.restaurant.customer-channel.confirmation.v1",
            "tenant_id": scope.tenant_id,
            "organization_unit_id": scope.organization_unit_id,
            "location_id": scope.location_id,
            "merchant_ref": str(scope.merchant_public_id),
            "context_binding_ref": str(scope.context_binding_public_id),
            "service_identity_ref": str(scope.service_identity_public_id),
            "service_mode": mode_code,
            "table_ref": str(table_ref) if table_ref else None,
            "contact_binding_ref": str(contact.binding_public_id) if contact else None,
            "delivery_address_binding_ref": str(address.binding_public_id) if address else None,
            "party_ref": str(contact.party_public_id) if contact else None,
            "lines": [_line_dict(line) for line in lines],
            "canonical_total": str(total),
            "currency": scope.currency,
            "policy_refs": policy_refs,
            "observed_quote_ref": request.get("observed_quote_ref"),
            "observed_quote_version": request.get("observed_quote_version"),
            "request": request,
        }
        return snapshot, tuple(lines)

    @staticmethod
    def _confirmation_projection(row: dict[str, Any]) -> ConfirmationProjection:
        snapshot = dict(row["authoritative_snapshot"])
        return ConfirmationProjection(
            UUID(str(row["public_id"])),
            UUID(snapshot["merchant_ref"]),
            int(snapshot["location_id"]),
            UUID(snapshot["context_binding_ref"]),
            snapshot["service_mode"],
            tuple(_line_from_dict(x) for x in snapshot["lines"]),
            Decimal(snapshot["canonical_total"]),
            snapshot["currency"],
            snapshot.get("observed_quote_ref"),
            snapshot.get("observed_quote_version"),
            tuple(snapshot.get("policy_refs") or ()),
            row["expires_at"],
            row["commercial_fingerprint"],
        )

    def confirm_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        payload: dict[str, Any],
        at: datetime | None = None,
    ) -> ConfirmationProjection:
        now = _utc(at)
        request = self._canonical_request(payload)
        snapshot, _ = self._build_snapshot(scope=scope, request=request, at=now)
        fingerprint = _fingerprint(snapshot)
        expires_at = now + timedelta(seconds=CONFIRMATION_TTL_SECONDS)
        row = self.repo.create_confirmation(
            public_id=uuid4(),
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            location_id=scope.location_id,
            merchant_public_id=scope.merchant_public_id,
            context_binding_public_id=scope.context_binding_public_id,
            service_mode=request["service_mode"],
            table_resource_public_id=UUID(request["table_ref"]) if request.get("table_ref") else None,
            contact_binding_public_id=UUID(request["contact_ref"]) if request.get("contact_ref") else None,
            delivery_address_binding_public_id=(
                UUID(request["delivery_address_ref"])
                if request.get("delivery_address_ref")
                else None
            ),
            authoritative_snapshot=snapshot,
            commercial_fingerprint=fingerprint,
            observed_quote_ref=request.get("observed_quote_ref"),
            observed_quote_version=request.get("observed_quote_version"),
            expires_at=expires_at,
        )
        return self._confirmation_projection(row)

    @staticmethod
    def _order_projection(order: Any) -> OrderProjection:
        state = getattr(getattr(order, "status", None), "value", getattr(order, "status", None))
        return OrderProjection(
            order.public_id,
            order.order_code,
            str(state),
            order.mode_code,
            int(order.row_version),
        )

    def submit_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        confirmation_ref: UUID,
        client_submit_ref: str,
        at: datetime | None = None,
    ) -> OrderProjection:
        now = _utc(at)
        _, submit_hash = _client_submit_ref(client_submit_ref)
        row = self.repo.confirmation(scope.tenant_id, confirmation_ref, lock=True)
        if row is None:
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )
        if (
            row["expires_at"] <= now
            or int(row["organization_unit_id"]) != scope.organization_unit_id
            or int(row["location_id"]) != scope.location_id
            or UUID(str(row["merchant_public_id"])) != scope.merchant_public_id
            or UUID(str(row["context_binding_public_id"])) != scope.context_binding_public_id
        ):
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )

        original_snapshot = dict(row["authoritative_snapshot"])
        rebuilt_snapshot, _ = self._build_snapshot(
            scope=scope,
            request=dict(original_snapshot["request"]),
            at=now,
        )
        if _fingerprint(rebuilt_snapshot) != row["commercial_fingerprint"]:
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )

        claimed = self.repo.claim_confirmation(
            tenant_id=scope.tenant_id,
            confirmation_public_id=confirmation_ref,
            client_submit_ref_hash=submit_hash,
        )
        if claimed.get("order_public_id"):
            order = self.adapters.r1_repo.order(
                scope.tenant_id,
                UUID(str(claimed["order_public_id"])),
            )
            if order is None:
                raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
            return self._order_projection(order)

        prefix = f"cc1:{submit_hash}"
        mode = self.adapters.r1.mode(scope.tenant_id, original_snapshot["service_mode"])
        table_ref = (
            UUID(original_snapshot["table_ref"])
            if original_snapshot.get("table_ref")
            else None
        )
        party_ref = (
            UUID(original_snapshot["party_ref"])
            if original_snapshot.get("party_ref")
            else None
        )
        session_ref = self.adapters.open_session_if_required(
            scope=scope,
            mode=mode,
            command_prefix=prefix,
            table_ref=table_ref,
            party_ref=party_ref,
            at=now,
        )
        order = self.adapters.open_order(
            scope=scope,
            mode_code=mode.mode_code,
            command_prefix=prefix,
            order_code=f"CC-{submit_hash[:12]}",
            session_ref=session_ref,
            party_ref=party_ref,
            at=now,
        )
        lines = tuple(_line_from_dict(x) for x in original_snapshot["lines"])
        for ordinal, line in enumerate(lines, start=1):
            before = {x.public_id for x in order.lines}
            order = self.adapters.add_line(
                scope=scope,
                order=order,
                line=line,
                command_key=f"{prefix}:line:{ordinal:04d}",
                at=now,
            )
            after = [x for x in order.lines if x.public_id not in before]
            if len(after) != 1:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            if line.modifier_selections:
                self.adapters.set_line_modifiers(
                    scope=scope,
                    order_line_public_id=after[0].public_id,
                    selections=line.modifier_selections,
                    command_key=f"{prefix}:modifier:{ordinal:04d}",
                    at=now,
                )
        submitted = self.adapters.submit_order(
            scope=scope,
            order=order,
            command_key=f"{prefix}:submit",
            at=now,
        )
        self.repo.bind_confirmation_order(
            tenant_id=scope.tenant_id,
            confirmation_public_id=confirmation_ref,
            order_public_id=submitted.public_id,
        )
        return self._order_projection(submitted)

    def reconcile_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        client_submit_ref: str,
    ) -> OrderProjection:
        _, submit_hash = _client_submit_ref(client_submit_ref)
        result = self.repo.command_order_result(
            scope.tenant_id,
            f"cc1:{submit_hash}:submit",
        )
        if result is None:
            raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
        order = self.adapters.r1_repo.order(scope.tenant_id, result)
        if order is None:
            raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
        return self._order_projection(order)

    def create_payment_request(
        self,
        *,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
    ) -> dict[str, Any]:
        order = self.adapters.r1_repo.order(scope.tenant_id, order_ref)
        if order is None:
            raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
        try:
            projection = self.adapters.payment_request(scope=scope, order_ref=order_ref)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if "METHOD" in code:
                raise H1BError("UNSUPPORTED_METHOD", correlation_ref=scope.correlation_ref) from exc
            if "POLICY" in code or "PAYMENT" in code:
                raise H1BError("PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=scope.correlation_ref) from exc
            raise H1BError("UNKNOWN_PAYMENT_REQUEST_RESULT", correlation_ref=scope.correlation_ref) from exc
        result = payment_projection_dict(projection)
        if len(result) != 13:
            raise H1BError("UNKNOWN_PAYMENT_REQUEST_RESULT", correlation_ref=scope.correlation_ref)
        return result
