from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from restaurant.r1.contracts import (
    AddLine,
    CancelOrder,
    ChangeOrderFulfillment,
    ChangeOrderLineQuantity,
    OrderStatus,
    RemoveOrderLine,
    SubmitOrder,
)
from shared_operations.so1.contracts import ScopeType

from .contracts import CONFIRMATION_TTL_SECONDS, H1BError, TrustedCheckoutScope
from .delivery_policy import normalized_address, select_delivery_policy
from .repository import SQLCatalogReadBindingRepository
from .service import (
    RestaurantCustomerChannelCheckoutAuthority,
    _fingerprint,
    _line_dict,
    _line_from_dict,
    _utc,
)


_ALLOWED_OPERATIONS = {
    "ADD_LINE",
    "REMOVE_LINE",
    "SET_QUANTITY",
    "SET_FULFILLMENT",
    "CANCEL_DRAFT",
}


def _client_command_ref(value: Any) -> tuple[str, str]:
    selected = str(value or "").strip()
    if not selected or len(selected.encode("utf-8")) > 160:
        raise H1BError("IDEMPOTENCY_CONFLICT")
    return selected, hashlib.sha256(selected.encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise H1BError("ORDER_NOT_READY") from exc
    if not selected.is_finite() or selected <= 0:
        raise H1BError("ORDER_NOT_READY")
    return selected


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:
        raise H1BError("ORDER_NOT_READY") from exc


class CustomerChannelDraftOrderAuthority:
    """Private Customer Channel draft facade over one canonical R1 order."""

    def __init__(self, session):
        self.session = session
        self.checkout = RestaurantCustomerChannelCheckoutAuthority(session)
        self.repo = self.checkout.repo
        self.adapters = self.checkout.adapters
        self.catalog_bindings = SQLCatalogReadBindingRepository(session)

    def trusted_scope(self, **kwargs) -> TrustedCheckoutScope:
        return self.checkout.trusted_scope(**kwargs)

    @staticmethod
    def _command_fingerprint(
        *,
        operation: str,
        draft_ref: UUID | None,
        expected_versions: dict[str, Any],
        body: dict[str, Any],
        scope: TrustedCheckoutScope,
    ) -> str:
        return _fingerprint(
            {
                "operation": operation,
                "draft_ref": str(draft_ref) if draft_ref else None,
                "expected_versions": expected_versions,
                "body": body,
                "context_binding_ref": str(scope.context_binding_public_id),
                "merchant_ref": str(scope.merchant_public_id),
                "location_id": scope.location_id,
            }
        )

    @staticmethod
    def _same_command(row: dict[str, Any], operation: str, fingerprint: str) -> bool:
        return (
            str(row["operation"]) == operation
            and str(row["request_fingerprint"]) == fingerprint
            and str(row["completion_state"]) == "completed"
        )

    def _binding_for_scope(
        self,
        scope: TrustedCheckoutScope,
        *,
        at: datetime,
    ):
        location_public_id = self.repo.location_public_id(
            scope.tenant_id, scope.location_id
        )
        rows = self.catalog_bindings.resolve(
            scope.merchant_public_id,
            location_public_id,
            at,
        )
        if len(rows) != 1:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        binding = rows[0]
        if (
            binding.tenant_id != scope.tenant_id
            or binding.merchant_public_id != scope.merchant_public_id
            or binding.location_public_id != location_public_id
            or not binding.enabled
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        return binding

    def _binding_for_draft(
        self,
        scope: TrustedCheckoutScope,
        draft: dict[str, Any],
        *,
        at: datetime,
    ):
        binding = self._binding_for_scope(scope, at=at)
        if (
            UUID(str(draft["catalog_binding_public_id"])) != binding.binding_ref
            or int(draft["catalog_binding_version"]) != binding.binding_version
        ):
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )
        return binding

    def _draft(
        self,
        scope: TrustedCheckoutScope,
        draft_ref: UUID,
        *,
        lock: bool = False,
    ) -> dict[str, Any]:
        row = self.repo.draft(scope.tenant_id, draft_ref, lock=lock)
        if row is None:
            raise H1BError("DRAFT_NOT_FOUND", correlation_ref=scope.correlation_ref)
        if (
            int(row["organization_unit_id"]) != scope.organization_unit_id
            or int(row["location_id"]) != scope.location_id
            or UUID(str(row["merchant_public_id"])) != scope.merchant_public_id
            or UUID(str(row["context_binding_public_id"]))
            != scope.context_binding_public_id
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        return row

    def _fulfillment(
        self,
        *,
        scope: TrustedCheckoutScope,
        service_mode: str,
        table_ref: UUID | None,
        contact_ref: UUID | None,
        delivery_address_ref: UUID | None,
        at: datetime,
    ):
        mode_code = str(service_mode or "").strip().lower()
        if mode_code not in {"dine_in", "takeaway", "delivery"}:
            raise H1BError("UNSUPPORTED_METHOD", correlation_ref=scope.correlation_ref)
        try:
            mode = self.adapters.r1.mode(scope.tenant_id, mode_code)
        except Exception as exc:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref) from exc
        if not mode.active:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        contact = None
        address = None
        if mode_code == "dine_in":
            if table_ref is None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            self.checkout._table_context(scope, table_ref)
            if delivery_address_ref is not None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            if contact_ref is not None:
                contact = self.checkout._bound_contact(
                    scope=scope,
                    binding_ref=contact_ref,
                    purpose="restaurant.customer_channel.contact",
                    contact_type=None,
                    at=at,
                )
        elif mode_code == "takeaway":
            if table_ref is not None or contact_ref is None or delivery_address_ref is not None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            contact = self.checkout._bound_contact(
                scope=scope,
                binding_ref=contact_ref,
                purpose="restaurant.customer_channel.contact",
                contact_type=None,
                at=at,
            )
        else:
            if table_ref is not None or contact_ref is None or delivery_address_ref is None:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            contact = self.checkout._bound_contact(
                scope=scope,
                binding_ref=contact_ref,
                purpose="restaurant.customer_channel.contact",
                contact_type=None,
                at=at,
            )
            address = self.checkout._bound_contact(
                scope=scope,
                binding_ref=delivery_address_ref,
                purpose="restaurant.customer_channel.delivery_address",
                contact_type="postal_address",
                at=at,
            )
            if address.party_public_id != contact.party_public_id:
                raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
            select_delivery_policy(
                self.repo.delivery_policies(
                    scope.tenant_id,
                    scope.organization_unit_id,
                    scope.location_id,
                ),
                address=normalized_address(address.contact_value, address.metadata),
                at=at,
            )
        return mode, (contact.party_public_id if contact else None)

    def _delivery_fee(
        self,
        *,
        scope: TrustedCheckoutScope,
        draft: dict[str, Any],
        at: datetime,
        currency: str | None = None,
    ):
        if str(draft["service_mode"]) != "delivery":
            return None, ()
        address_ref = draft.get("delivery_address_binding_public_id")
        if not address_ref:
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)
        address = self.checkout._bound_contact(
            scope=scope,
            binding_ref=UUID(str(address_ref)),
            purpose="restaurant.customer_channel.delivery_address",
            contact_type="postal_address",
            at=at,
        )
        policy = select_delivery_policy(
            self.repo.delivery_policies(
                scope.tenant_id,
                scope.organization_unit_id,
                scope.location_id,
            ),
            address=normalized_address(address.contact_value, address.metadata),
            at=at,
        )
        fee = self.adapters.resolve_fixed_fee_line(
            scope=scope,
            catalog_entry_ref=policy.fee_catalog_entry_public_id,
            price_ref=policy.fee_price_public_id,
            at=at,
            currency=currency or scope.currency,
        )
        if fee.unit_price == Decimal("0"):
            return None, (f"delivery:{policy.public_id}:v{policy.policy_version}",)
        return fee, (f"delivery:{policy.public_id}:v{policy.policy_version}",)

    def _modifier_refs(self, scope: TrustedCheckoutScope, line_ref: UUID) -> tuple[UUID, ...]:
        selected = self.adapters.r2_repo.modifier_set(scope.tenant_id, line_ref)
        if selected is None:
            return ()
        refs: list[UUID] = []
        for item in selected.selections:
            if Decimal(item.price_amount_snapshot) != Decimal("0"):
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            refs.append(item.option_public_id)
        return tuple(sorted(refs, key=str))

    def _binding_map(
        self, scope: TrustedCheckoutScope, draft_ref: UUID
    ) -> dict[UUID, UUID]:
        rows = self.repo.draft_line_bindings(scope.tenant_id, draft_ref)
        return {
            UUID(str(row["order_line_public_id"])): UUID(str(row["item_public_id"]))
            for row in rows
        }

    def _projection(
        self,
        scope: TrustedCheckoutScope,
        draft: dict[str, Any],
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _utc(at)
        order = self.adapters.r1_repo.order(
            scope.tenant_id, UUID(str(draft["order_public_id"]))
        )
        if order is None:
            raise H1BError("DRAFT_NOT_FOUND", correlation_ref=scope.correlation_ref)

        stored_binding = self.repo.catalog_binding_by_ref(
            scope.tenant_id, UUID(str(draft["catalog_binding_public_id"]))
        )
        binding_current = False
        if (
            stored_binding is not None
            and stored_binding.binding_version == int(draft["catalog_binding_version"])
        ):
            try:
                self._binding_for_draft(scope, draft, at=now)
                binding_current = True
            except H1BError:
                binding_current = False

        if order.status is OrderStatus.OPEN and stored_binding is None:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        bindings = self._binding_map(scope, UUID(str(draft["public_id"])))
        lines: list[dict[str, Any]] = []
        subtotal = Decimal("0")
        line_currencies: set[str] = set()
        for line in order.lines:
            item_ref = bindings.get(line.public_id)
            if item_ref is None:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            total = line.quantity * line.unit_price_snapshot
            subtotal += total
            line_currencies.add(str(line.currency))
            lines.append(
                {
                    "line_ref": str(line.public_id),
                    "item_ref": str(item_ref),
                    "quantity": str(line.quantity),
                    "modifier_refs": [str(x) for x in self._modifier_refs(scope, line.public_id)],
                    "unit_price": str(line.unit_price_snapshot),
                    "line_total": str(total),
                    "currency": line.currency,
                    "availability": (
                        "orderable"
                        if order.status is OrderStatus.OPEN and binding_current
                        else "not_orderable"
                    ),
                }
            )

        if len(line_currencies) > 1:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        projection_currency = (
            next(iter(line_currencies))
            if line_currencies
            else (
                stored_binding.currency
                if stored_binding is not None
                else scope.currency
            )
        )

        fulfillment_fee = Decimal("0")
        if order.status is OrderStatus.OPEN and binding_current:
            fee, _ = self._delivery_fee(
                scope=scope,
                draft=draft,
                at=now,
                currency=projection_currency,
            )
            if fee is not None:
                fulfillment_fee = fee.total
        total = subtotal + fulfillment_fee
        state = {
            "open": "DRAFT",
            "submitted": "SUBMITTED",
            "cancelled": "CANCELLED",
        }[order.status.value]
        return {
            "draft_ref": str(draft["public_id"]),
            "draft_version": int(draft["row_version"]),
            "order_ref": str(order.public_id),
            "order_version": int(order.row_version),
            "order_state": state,
            "catalog_binding_ref": str(draft["catalog_binding_public_id"]),
            "catalog_binding_version": int(draft["catalog_binding_version"]),
            "fulfillment_mode": str(draft["service_mode"]),
            "table_ref": (
                str(draft["table_resource_public_id"])
                if draft.get("table_resource_public_id")
                else None
            ),
            "contact_ref": (
                str(draft["contact_binding_public_id"])
                if draft.get("contact_binding_public_id")
                else None
            ),
            "delivery_address_ref": (
                str(draft["delivery_address_binding_public_id"])
                if draft.get("delivery_address_binding_public_id")
                else None
            ),
            "lines": lines,
            "subtotal": str(subtotal),
            "fulfillment_fee": str(fulfillment_fee),
            "canonical_total": str(total),
            "currency": projection_currency,
            "commercial_orderability": (
                order.status is OrderStatus.OPEN and binding_current
            ),
            "confirmation_state": (
                "required"
                if order.status is OrderStatus.OPEN
                else (
                    "submitted"
                    if order.status is OrderStatus.SUBMITTED
                    else "not_applicable"
                )
            ),
        }

    def _draft_snapshot(
        self,
        scope: TrustedCheckoutScope,
        draft: dict[str, Any],
        *,
        at: datetime,
    ) -> dict[str, Any]:
        binding = self._binding_for_draft(scope, draft, at=at)
        order = self.adapters.r1_repo.order(
            scope.tenant_id, UUID(str(draft["order_public_id"]))
        )
        if order is None or order.status is not OrderStatus.OPEN:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        bindings = self._binding_map(scope, UUID(str(draft["public_id"])))
        lines = []
        for line in order.lines:
            item_ref = bindings.get(line.public_id)
            if item_ref is None:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            option_refs = self._modifier_refs(scope, line.public_id)
            resolved = self.adapters.resolve_item_line(
                scope=scope,
                catalog_entry_ref=item_ref,
                quantity=line.quantity,
                option_refs=option_refs,
                at=at,
                currency=binding.currency,
                catalog_public_id=binding.catalog_public_id,
                price_code=binding.price_code,
                price_scope_type=ScopeType(binding.scope_type),
                price_scope_id=binding.scope_id,
            )
            if (
                resolved.target_type != line.target_type.value
                or resolved.target_ref != line.target_public_id
                or resolved.price_ref != line.price_public_id
                or resolved.quantity != line.quantity
                or resolved.unit_price != line.unit_price_snapshot
                or resolved.currency != line.currency
            ):
                raise H1BError(
                    "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                    correlation_ref=scope.correlation_ref,
                )
            value = _line_dict(resolved)
            value["order_line_ref"] = str(line.public_id)
            lines.append(value)
        fee, policy_refs = self._delivery_fee(
            scope=scope,
            draft=draft,
            at=at,
            currency=binding.currency,
        )
        if fee is not None:
            value = _line_dict(fee)
            value["order_line_ref"] = None
            lines.append(value)
        if not lines:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        currencies = {str(x["currency"]) for x in lines}
        if currencies != {binding.currency}:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        total = sum(
            (Decimal(str(x["quantity"])) * Decimal(str(x["unit_price"])) for x in lines),
            Decimal("0"),
        )
        return {
            "schema": "xbos.restaurant.customer-channel.draft-confirmation.v1",
            "draft_ref": str(draft["public_id"]),
            "draft_version": int(draft["row_version"]),
            "order_ref": str(order.public_id),
            "order_version": int(order.row_version),
            "tenant_id": scope.tenant_id,
            "organization_unit_id": scope.organization_unit_id,
            "location_id": scope.location_id,
            "merchant_ref": str(scope.merchant_public_id),
            "context_binding_ref": str(scope.context_binding_public_id),
            "service_identity_ref": str(scope.service_identity_public_id),
            "catalog_binding_ref": str(binding.binding_ref),
            "catalog_binding_version": int(binding.binding_version),
            "catalog_public_id": str(binding.catalog_public_id),
            "price_code": binding.price_code,
            "service_mode": str(draft["service_mode"]),
            "table_ref": (
                str(draft["table_resource_public_id"])
                if draft.get("table_resource_public_id")
                else None
            ),
            "contact_binding_ref": (
                str(draft["contact_binding_public_id"])
                if draft.get("contact_binding_public_id")
                else None
            ),
            "delivery_address_binding_ref": (
                str(draft["delivery_address_binding_public_id"])
                if draft.get("delivery_address_binding_public_id")
                else None
            ),
            "lines": lines,
            "canonical_total": str(total),
            "currency": binding.currency,
            "policy_refs": list(policy_refs),
        }

    def create_draft(
        self,
        *,
        scope: TrustedCheckoutScope,
        client_command_ref: str,
        service_mode: str,
        table_ref: UUID | None = None,
        contact_ref: UUID | None = None,
        delivery_address_ref: UUID | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _utc(at)
        _, command_hash = _client_command_ref(client_command_ref)
        body = {
            "service_mode": str(service_mode or "").strip().lower(),
            "table_ref": str(table_ref) if table_ref else None,
            "contact_ref": str(contact_ref) if contact_ref else None,
            "delivery_address_ref": str(delivery_address_ref) if delivery_address_ref else None,
        }
        fingerprint = self._command_fingerprint(
            operation="CREATE_DRAFT",
            draft_ref=None,
            expected_versions={},
            body=body,
            scope=scope,
        )
        replay = self.repo.command_result(scope.tenant_id, command_hash, lock=True)
        if replay is not None:
            if not self._same_command(replay, "CREATE_DRAFT", fingerprint):
                raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=scope.correlation_ref)
            draft = self._draft(scope, UUID(str(replay["draft_public_id"])))
            return self._projection(scope, draft, at=now)

        binding = self._binding_for_scope(scope, at=now)
        mode, party_ref = self._fulfillment(
            scope=scope,
            service_mode=body["service_mode"],
            table_ref=table_ref,
            contact_ref=contact_ref,
            delivery_address_ref=delivery_address_ref,
            at=now,
        )
        prefix = f"cc2:{command_hash}"
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
            order_code=f"CCD-{command_hash[:12]}",
            session_ref=session_ref,
            party_ref=party_ref,
            at=now,
        )
        draft_ref = uuid4()
        draft = self.repo.create_draft(
            public_id=draft_ref,
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            location_id=scope.location_id,
            merchant_public_id=scope.merchant_public_id,
            context_binding_public_id=scope.context_binding_public_id,
            catalog_binding_public_id=binding.binding_ref,
            catalog_binding_version=binding.binding_version,
            order_public_id=order.public_id,
            service_mode=mode.mode_code,
            table_resource_public_id=table_ref,
            contact_binding_public_id=contact_ref,
            delivery_address_binding_public_id=delivery_address_ref,
        )
        self.repo.record_command_result(
            tenant_id=scope.tenant_id,
            client_command_ref_hash=command_hash,
            operation="CREATE_DRAFT",
            request_fingerprint=fingerprint,
            draft_public_id=draft_ref,
            order_public_id=order.public_id,
        )
        return self._projection(scope, draft, at=now)

    def read_draft(
        self,
        *,
        scope: TrustedCheckoutScope,
        draft_ref: UUID,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        return self._projection(scope, self._draft(scope, draft_ref), at=at)

    def reconcile_command(
        self,
        *,
        scope: TrustedCheckoutScope,
        client_command_ref: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        _, command_hash = _client_command_ref(client_command_ref)
        row = self.repo.command_result(scope.tenant_id, command_hash)
        if row is None:
            raise H1BError("COMMAND_RESULT_UNKNOWN", correlation_ref=scope.correlation_ref)
        draft = self._draft(scope, UUID(str(row["draft_public_id"])))
        order = self.adapters.r1_repo.order(
            scope.tenant_id, UUID(str(draft["order_public_id"]))
        )
        if order is None:
            raise H1BError("COMMAND_RESULT_UNKNOWN", correlation_ref=scope.correlation_ref)
        projection = None
        try:
            projection = self._projection(scope, draft, at=at)
        except H1BError:
            # A completed mutation remains exactly reconcilable even if later
            # catalog or fulfillment policy makes a fresh commerce projection
            # unavailable. Never blind-retry the effect.
            projection = None
        return {
            "operation": str(row["operation"]),
            "completion_state": str(row["completion_state"]),
            "draft_ref": str(row["draft_public_id"]),
            "draft_version": int(draft["row_version"]),
            "line_ref": str(row["line_public_id"]) if row.get("line_public_id") else None,
            "order_ref": str(row["order_public_id"]) if row.get("order_public_id") else None,
            "order_version": int(order.row_version),
            "draft": projection,
        }

    def reconcile_create(
        self,
        *,
        scope: TrustedCheckoutScope,
        client_command_ref: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        result = self.reconcile_command(
            scope=scope, client_command_ref=client_command_ref, at=at
        )
        if result["operation"] != "CREATE_DRAFT":
            raise H1BError("COMMAND_RESULT_UNKNOWN", correlation_ref=scope.correlation_ref)
        if result["draft"] is not None:
            return result["draft"]
        return self.read_draft(
            scope=scope,
            draft_ref=UUID(str(result["draft_ref"])),
            at=at,
        )

    def mutate_draft(
        self,
        *,
        scope: TrustedCheckoutScope,
        draft_ref: UUID,
        payload: dict[str, Any],
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _utc(at)
        if not isinstance(payload, dict):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        operation = str(payload.get("operation") or "").strip().upper()
        if operation not in _ALLOWED_OPERATIONS:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        shapes = {
            "ADD_LINE": {
                "operation",
                "client_command_ref",
                "expected_draft_version",
                "item_ref",
                "quantity",
                "modifier_refs",
            },
            "REMOVE_LINE": {
                "operation",
                "client_command_ref",
                "expected_draft_version",
                "line_ref",
                "expected_line_version",
            },
            "SET_QUANTITY": {
                "operation",
                "client_command_ref",
                "expected_draft_version",
                "line_ref",
                "expected_line_version",
                "quantity",
            },
            "SET_FULFILLMENT": {
                "operation",
                "client_command_ref",
                "expected_draft_version",
                "service_mode",
                "table_ref",
                "contact_ref",
                "delivery_address_ref",
            },
            "CANCEL_DRAFT": {
                "operation",
                "client_command_ref",
                "expected_draft_version",
                "reason_code",
            },
        }
        if set(payload) != shapes[operation]:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        _, command_hash = _client_command_ref(payload["client_command_ref"])
        try:
            expected_draft_version = int(payload["expected_draft_version"])
        except Exception as exc:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref) from exc
        if expected_draft_version < 1:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)

        body = {
            key: (
                [str(x) for x in value]
                if key == "modifier_refs" and isinstance(value, list)
                else str(value)
                if key.endswith("_ref") and value is not None
                else value
            )
            for key, value in payload.items()
            if key not in {"client_command_ref", "expected_draft_version"}
        }
        expected_versions: dict[str, Any] = {"draft": expected_draft_version}
        if "expected_line_version" in payload:
            try:
                expected_versions["line"] = int(payload["expected_line_version"])
            except Exception as exc:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref) from exc

        fingerprint = self._command_fingerprint(
            operation=operation,
            draft_ref=draft_ref,
            expected_versions=expected_versions,
            body=body,
            scope=scope,
        )
        replay = self.repo.command_result(scope.tenant_id, command_hash, lock=True)
        if replay is not None:
            if not self._same_command(replay, operation, fingerprint):
                raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=scope.correlation_ref)
            return self._projection(
                scope,
                self._draft(scope, UUID(str(replay["draft_public_id"]))),
                at=now,
            )

        draft = self._draft(scope, draft_ref, lock=True)
        if (
            str(draft["lifecycle_status"]) != "open"
            or int(draft["row_version"]) != expected_draft_version
        ):
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        binding = self._binding_for_draft(scope, draft, at=now)
        order = self.adapters.r1_repo.order(
            scope.tenant_id, UUID(str(draft["order_public_id"]))
        )
        if order is None or order.status is not OrderStatus.OPEN:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)

        result_line_ref: UUID | None = None

        if operation == "ADD_LINE":
            item_ref = _uuid(payload["item_ref"])
            quantity = _decimal(payload["quantity"])
            raw_modifiers = payload["modifier_refs"]
            if not isinstance(raw_modifiers, list):
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            modifier_refs = tuple(_uuid(x) for x in raw_modifiers)
            resolved = self.adapters.resolve_item_line(
                scope=scope,
                catalog_entry_ref=item_ref,
                quantity=quantity,
                option_refs=modifier_refs,
                at=now,
                currency=binding.currency,
                catalog_public_id=binding.catalog_public_id,
                price_code=binding.price_code,
                price_scope_type=ScopeType(binding.scope_type),
                price_scope_id=binding.scope_id,
            )
            before = {x.public_id for x in order.lines}
            from restaurant.r1.contracts import TargetType as R1TargetType
            order = self.adapters.r1.add_line(
                AddLine(
                    f"cc2:{command_hash}:add",
                    scope.tenant_id,
                    order.public_id,
                    order.row_version,
                    R1TargetType(resolved.target_type),
                    resolved.target_ref,
                    resolved.price_ref,
                    resolved.quantity,
                    now,
                )
            )
            added = [x for x in order.lines if x.public_id not in before]
            if len(added) != 1:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            result_line_ref = added[0].public_id
            if resolved.modifier_selections:
                self.adapters.set_line_modifiers(
                    scope=scope,
                    order_line_public_id=result_line_ref,
                    selections=resolved.modifier_selections,
                    command_key=f"cc2:{command_hash}:modifier",
                    at=now,
                )
            self.repo.bind_draft_line(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                order_line_public_id=result_line_ref,
                item_public_id=item_ref,
            )
            draft = self.repo.touch_draft(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                expected_version=expected_draft_version,
            )

        elif operation in {"REMOVE_LINE", "SET_QUANTITY"}:
            line_ref = _uuid(payload["line_ref"])
            mappings = self._binding_map(scope, draft_ref)
            if line_ref not in mappings:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            expected_line_version = int(payload["expected_line_version"])
            if operation == "REMOVE_LINE":
                order = self.adapters.r1.remove_order_line(
                    RemoveOrderLine(
                        f"cc2:{command_hash}:remove",
                        scope.tenant_id,
                        order.public_id,
                        line_ref,
                        order.row_version,
                        expected_line_version,
                        now,
                    )
                )
            else:
                order = self.adapters.r1.change_line_quantity(
                    ChangeOrderLineQuantity(
                        f"cc2:{command_hash}:quantity",
                        scope.tenant_id,
                        order.public_id,
                        line_ref,
                        order.row_version,
                        expected_line_version,
                        _decimal(payload["quantity"]),
                        now,
                    )
                )
            result_line_ref = line_ref
            draft = self.repo.touch_draft(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                expected_version=expected_draft_version,
            )

        elif operation == "SET_FULFILLMENT":
            table_ref = _uuid(payload["table_ref"]) if payload["table_ref"] is not None else None
            contact_ref = _uuid(payload["contact_ref"]) if payload["contact_ref"] is not None else None
            address_ref = (
                _uuid(payload["delivery_address_ref"])
                if payload["delivery_address_ref"] is not None
                else None
            )
            mode, party_ref = self._fulfillment(
                scope=scope,
                service_mode=str(payload["service_mode"]),
                table_ref=table_ref,
                contact_ref=contact_ref,
                delivery_address_ref=address_ref,
                at=now,
            )
            session_ref = self.adapters.open_session_if_required(
                scope=scope,
                mode=mode,
                command_prefix=f"cc2:{command_hash}:fulfillment",
                table_ref=table_ref,
                party_ref=party_ref,
                at=now,
            )
            order = self.adapters.r1.change_order_fulfillment(
                ChangeOrderFulfillment(
                    f"cc2:{command_hash}:fulfillment",
                    scope.tenant_id,
                    order.public_id,
                    order.row_version,
                    mode.mode_code,
                    now,
                    session_public_id=session_ref,
                    party_public_id=party_ref,
                )
            )
            draft = self.repo.update_draft_fulfillment(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                expected_version=expected_draft_version,
                service_mode=mode.mode_code,
                table_resource_public_id=table_ref,
                contact_binding_public_id=contact_ref,
                delivery_address_binding_public_id=address_ref,
            )

        else:
            reason = str(payload["reason_code"] or "").strip()
            if not reason:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            order = self.adapters.r1.cancel_order(
                CancelOrder(
                    f"cc2:{command_hash}:cancel",
                    scope.tenant_id,
                    order.public_id,
                    order.row_version,
                    now,
                    reason,
                )
            )
            draft = self.repo.transition_draft(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                expected_version=expected_draft_version,
                to_state="cancelled",
            )

        if draft is None:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)

        self.repo.record_command_result(
            tenant_id=scope.tenant_id,
            client_command_ref_hash=command_hash,
            operation=operation,
            request_fingerprint=fingerprint,
            draft_public_id=draft_ref,
            line_public_id=result_line_ref,
            order_public_id=order.public_id,
        )
        return self._projection(scope, draft, at=now)

    def confirm_draft(
        self,
        *,
        scope: TrustedCheckoutScope,
        draft_ref: UUID,
        at: datetime | None = None,
    ):
        now = _utc(at)
        draft = self._draft(scope, draft_ref, lock=True)
        if str(draft["lifecycle_status"]) != "open":
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        snapshot = self._draft_snapshot(scope, draft, at=now)
        fingerprint = _fingerprint(snapshot)
        expires_at = now + timedelta(seconds=CONFIRMATION_TTL_SECONDS)
        row = self.repo.create_confirmation(
            public_id=uuid4(),
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            location_id=scope.location_id,
            merchant_public_id=scope.merchant_public_id,
            context_binding_public_id=scope.context_binding_public_id,
            service_mode=str(draft["service_mode"]),
            table_resource_public_id=(
                UUID(str(draft["table_resource_public_id"]))
                if draft.get("table_resource_public_id")
                else None
            ),
            contact_binding_public_id=(
                UUID(str(draft["contact_binding_public_id"]))
                if draft.get("contact_binding_public_id")
                else None
            ),
            delivery_address_binding_public_id=(
                UUID(str(draft["delivery_address_binding_public_id"]))
                if draft.get("delivery_address_binding_public_id")
                else None
            ),
            authoritative_snapshot=snapshot,
            commercial_fingerprint=fingerprint,
            observed_quote_ref=None,
            observed_quote_version=None,
            expires_at=expires_at,
        )
        return self.checkout._confirmation_projection(row)

    def submit_draft(
        self,
        *,
        scope: TrustedCheckoutScope,
        draft_ref: UUID,
        confirmation_ref: UUID,
        client_submit_ref: str,
        at: datetime | None = None,
    ):
        now = _utc(at)
        draft = self._draft(scope, draft_ref, lock=True)
        row = self.repo.confirmation(scope.tenant_id, confirmation_ref, lock=True)
        if row is None:
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )
        snapshot = dict(row["authoritative_snapshot"])
        if (
            snapshot.get("schema")
            != "xbos.restaurant.customer-channel.draft-confirmation.v1"
            or snapshot.get("draft_ref") != str(draft_ref)
            or snapshot.get("order_ref") != str(draft["order_public_id"])
            or row["expires_at"] <= now
            or int(row["organization_unit_id"]) != scope.organization_unit_id
            or int(row["location_id"]) != scope.location_id
            or UUID(str(row["merchant_public_id"])) != scope.merchant_public_id
            or UUID(str(row["context_binding_public_id"]))
            != scope.context_binding_public_id
        ):
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )

        selected = str(client_submit_ref or "").strip()
        if not selected or len(selected.encode("utf-8")) > 160:
            raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=scope.correlation_ref)
        submit_hash = hashlib.sha256(selected.encode("utf-8")).hexdigest()
        claimed = self.repo.claim_confirmation(
            tenant_id=scope.tenant_id,
            confirmation_public_id=confirmation_ref,
            client_submit_ref_hash=submit_hash,
        )
        if claimed.get("order_public_id"):
            if UUID(str(claimed["order_public_id"])) != UUID(str(draft["order_public_id"])):
                raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=scope.correlation_ref)
            order = self.adapters.r1_repo.order(
                scope.tenant_id, UUID(str(claimed["order_public_id"]))
            )
            if order is None:
                raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
            return self.checkout._order_projection(order)

        if (
            str(draft["lifecycle_status"]) != "open"
            or int(draft["row_version"]) != int(snapshot.get("draft_version", -1))
        ):
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        current = self._draft_snapshot(scope, draft, at=now)
        if _fingerprint(current) != row["commercial_fingerprint"]:
            raise H1BError(
                "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED",
                correlation_ref=scope.correlation_ref,
            )
        order = self.adapters.r1_repo.order(
            scope.tenant_id, UUID(str(draft["order_public_id"]))
        )
        if order is None or order.status is not OrderStatus.OPEN:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)

        fee_lines = [x for x in snapshot["lines"] if x.get("line_kind") == "delivery_fee"]
        if len(fee_lines) > 1:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        if fee_lines:
            fee = _line_from_dict(fee_lines[0])
            from restaurant.r1.contracts import TargetType as R1TargetType
            before = {x.public_id for x in order.lines}
            order = self.adapters.r1.add_line(
                AddLine(
                    f"cc1:{submit_hash}:delivery-fee",
                    scope.tenant_id,
                    order.public_id,
                    order.row_version,
                    R1TargetType(fee.target_type),
                    fee.target_ref,
                    fee.price_ref,
                    fee.quantity,
                    now,
                )
            )
            added = [x for x in order.lines if x.public_id not in before]
            if len(added) != 1:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            self.repo.bind_draft_line(
                tenant_id=scope.tenant_id,
                draft_public_id=draft_ref,
                order_line_public_id=added[0].public_id,
                item_public_id=fee.catalog_entry_ref,
            )

        submitted = self.adapters.r1.submit_order(
            SubmitOrder(
                f"cc1:{submit_hash}:submit",
                scope.tenant_id,
                order.public_id,
                order.row_version,
                now,
            )
        )
        self.repo.bind_confirmation_order(
            tenant_id=scope.tenant_id,
            confirmation_public_id=confirmation_ref,
            order_public_id=submitted.public_id,
        )
        transitioned = self.repo.transition_draft(
            tenant_id=scope.tenant_id,
            draft_public_id=draft_ref,
            expected_version=int(draft["row_version"]),
            to_state="submitted",
        )
        if transitioned is None:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        return self.checkout._order_projection(submitted)

    def reconcile_submit(
        self,
        *,
        scope: TrustedCheckoutScope,
        client_submit_ref: str,
    ):
        projection = self.checkout.reconcile_order(
            scope=scope, client_submit_ref=client_submit_ref
        )
        draft = self.repo.draft_by_order(scope.tenant_id, projection.order_ref)
        if draft is not None:
            self._draft(scope, UUID(str(draft["public_id"])))
        return projection

    def read_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        draft = self.repo.draft_by_order(scope.tenant_id, order_ref)
        if draft is None:
            raise H1BError("DRAFT_NOT_FOUND", correlation_ref=scope.correlation_ref)
        draft = self._draft(scope, UUID(str(draft["public_id"])))
        return self._projection(scope, draft, at=at)

    def cancel_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
        client_command_ref: str,
        expected_draft_version: int,
        reason_code: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _utc(at)
        draft = self.repo.draft_by_order(scope.tenant_id, order_ref, lock=True)
        if draft is None:
            raise H1BError("DRAFT_NOT_FOUND", correlation_ref=scope.correlation_ref)
        draft = self._draft(scope, UUID(str(draft["public_id"])), lock=True)
        _, command_hash = _client_command_ref(client_command_ref)
        body = {"reason_code": str(reason_code or "").strip(), "order_ref": str(order_ref)}
        fingerprint = self._command_fingerprint(
            operation="CANCEL_ORDER",
            draft_ref=UUID(str(draft["public_id"])),
            expected_versions={"draft": int(expected_draft_version)},
            body=body,
            scope=scope,
        )
        replay = self.repo.command_result(scope.tenant_id, command_hash, lock=True)
        if replay is not None:
            if not self._same_command(replay, "CANCEL_ORDER", fingerprint):
                raise H1BError("IDEMPOTENCY_CONFLICT", correlation_ref=scope.correlation_ref)
            return self._projection(scope, draft, at=now)
        order = self.adapters.r1_repo.order(scope.tenant_id, order_ref)
        if (
            order is None
            or order.status is not OrderStatus.OPEN
            or str(draft["lifecycle_status"]) != "open"
            or int(draft["row_version"]) != int(expected_draft_version)
            or not body["reason_code"]
        ):
            # Submitted cancellation intentionally fails closed here. No refund semantics.
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        order = self.adapters.r1.cancel_order(
            CancelOrder(
                f"cc2:{command_hash}:cancel-order",
                scope.tenant_id,
                order_ref,
                order.row_version,
                now,
                body["reason_code"],
            )
        )
        transitioned = self.repo.transition_draft(
            tenant_id=scope.tenant_id,
            draft_public_id=UUID(str(draft["public_id"])),
            expected_version=int(expected_draft_version),
            to_state="cancelled",
        )
        if transitioned is None:
            raise H1BError("DRAFT_STATE_CONFLICT", correlation_ref=scope.correlation_ref)
        self.repo.record_command_result(
            tenant_id=scope.tenant_id,
            client_command_ref_hash=command_hash,
            operation="CANCEL_ORDER",
            request_fingerprint=fingerprint,
            draft_public_id=UUID(str(draft["public_id"])),
            order_public_id=order.public_id,
        )
        return self._projection(scope, transitioned, at=now)
