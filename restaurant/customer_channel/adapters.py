from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from core.platform.interaction.sql_repository import SQLInteractionRepository
from core.platform.operating_context.service import OperatingContextAuthority
from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
from core.platform.structure.service import StructuralAuthority
from core.platform.structure.sql_repository import SQLStructuralRepository
from restaurant.c3.adapters import (
    NeutralFinancePaymentRequestAdapter,
    PaymentPolicyAdapter,
    R1CheckoutAdapter,
    StructuralScopeAdapter,
)
from restaurant.c3.contracts import TrustedCheckoutContext
from restaurant.c3.service import CustomerSafeCheckoutPaymentRequestService
from restaurant.r1.contracts import (
    AddLine,
    OpenOrder,
    OpenSession,
    ResourceRole,
    SubmitOrder,
    TargetType as R1TargetType,
)
from restaurant.r1.service import R1Authority
from restaurant.r1.sql_repository import SQLR1Repository
from restaurant.r2.contracts import ModifierSelection, SetLineModifiers
from restaurant.r2.service import R2Authority
from restaurant.r2.sql_repository import SQLR2Repository
from shared_operations.so1.contracts import ResolvePrice, ScopeType, TargetType
from shared_operations.so1.sql_repository import SQLSO1Repository

from .contracts import AuthoritativeLine, H1BError, PRICE_CODE, TrustedCheckoutScope
from .repository import CustomerChannelRepository


class AcceptedAuthorityAdapters:
    """Composition over already accepted XBOS authority surfaces."""

    def __init__(self, session):
        self.session = session
        self.repo = CustomerChannelRepository(session)
        self.interaction = SQLInteractionRepository(session)
        self.structure = StructuralAuthority(SQLStructuralRepository(session))
        self.so1_repo = SQLSO1Repository(session)
        self.r1_repo = SQLR1Repository(session)
        self.r2_repo = SQLR2Repository(session)
        self.r1 = self._r1_authority()
        self.r2 = self._r2_authority()
        self.c3 = CustomerSafeCheckoutPaymentRequestService(
            restaurant=R1CheckoutAdapter(self.r1),
            structure=StructuralScopeAdapter(self.structure),
            payment_policy=PaymentPolicyAdapter(
                OperatingContextAuthority(SQLOperatingContextRepository(session))
            ),
            finance=NeutralFinancePaymentRequestAdapter(),
        )

    def _r1_authority(self) -> R1Authority:
        allow = lambda tenant, permission, scope, scope_id: True
        return R1Authority(
            self.r1_repo,
            resource_resolver=self.repo.resource,
            party_resolver=self.repo.party,
            identity_resolver=self.repo.identity,
            offer_resolver=self.so1_repo.offer,
            atomic_unit_resolver=self.so1_repo.atomic_unit,
            price_resolver=self.so1_repo.price,
            reservation_resolver=lambda tenant_id, public_id: None,
            authorize=allow,
        )

    def _r2_authority(self) -> R2Authority:
        allow = lambda tenant, permission, scope, scope_id: True
        return R2Authority(
            self.r2_repo,
            catalog_resolver=self.so1_repo.catalog,
            catalog_entry_resolver=self.so1_repo.catalog_entry,
            atomic_unit_resolver=self.so1_repo.atomic_unit,
            offer_resolver=self.so1_repo.offer,
            price_resolver=self.so1_repo.price,
            resource_resolver=self.repo.resource,
            order_resolver=self.r1_repo.order,
            order_line_resolver=self.repo.order_line,
            party_resolver=self.repo.party,
            authorize=allow,
        )

    @staticmethod
    def _effective(value: Any, at: datetime) -> bool:
        return (
            bool(getattr(value, "active", True))
            and getattr(value, "effective_from", at) <= at
            and (getattr(value, "effective_to", None) is None or at < getattr(value, "effective_to"))
        )

    def resolve_item_line(
        self,
        *,
        scope: TrustedCheckoutScope,
        catalog_entry_ref: UUID,
        quantity: Decimal,
        option_refs: tuple[UUID, ...],
        at: datetime,
        currency: str,
    ) -> AuthoritativeLine:
        entry = self.so1_repo.catalog_entry(scope.tenant_id, catalog_entry_ref)
        if entry is None or not entry.enabled or not self._effective(entry, at):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        catalog = self.so1_repo.catalog(scope.tenant_id, entry.catalog_public_id)
        if catalog is None or not self._effective(catalog, at):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        if not self.repo.menu_entry_is_current(scope.tenant_id, entry.public_id, at=at):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        try:
            price = self.so1_repo.resolve_price(
                ResolvePrice(
                    scope.tenant_id,
                    entry.target_type,
                    entry.target_public_id,
                    PRICE_CODE,
                    currency,
                    at,
                    ScopeType.LOCATION,
                    scope.location_id,
                )
            )
        except Exception as exc:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref) from exc
        if price is None:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        selections = self.resolve_modifier_selections(
            scope=scope,
            catalog_entry_ref=entry.public_id,
            option_refs=option_refs,
            at=at,
            currency=currency,
        )
        return AuthoritativeLine(
            entry.public_id,
            entry.target_type.value,
            entry.target_public_id,
            price.public_id,
            quantity,
            Decimal(price.amount),
            price.currency,
            int(entry.row_version),
            int(price.row_version),
            tuple(sorted(option_refs, key=str)),
            selections,
            "item",
        )

    def resolve_modifier_selections(
        self,
        *,
        scope: TrustedCheckoutScope,
        catalog_entry_ref: UUID,
        option_refs: tuple[UUID, ...],
        at: datetime,
        currency: str,
    ) -> tuple[dict[str, Any], ...]:
        if len(set(option_refs)) != len(option_refs):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        configs = self.r2_repo.modifier_configuration(scope.tenant_id, catalog_entry_ref, at)
        by_option: dict[UUID, tuple[Any, Any]] = {}
        for cfg in configs:
            for option in cfg.options:
                by_option[option.public_id] = (cfg.group, option)
        selected: dict[UUID, list[tuple[Any, Any]]] = {}
        normalized: list[dict[str, Any]] = []
        for option_ref in option_refs:
            pair = by_option.get(option_ref)
            if pair is None:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            group, option = pair
            if not option.active:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            if option.price_public_id is not None:
                price = self.so1_repo.price(scope.tenant_id, option.price_public_id)
                if price is None or not self._effective(price, at) or price.currency != currency:
                    raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
                if Decimal(price.amount) != Decimal("0"):
                    # Accepted C3 derives only from R1 obligation lines. A priced
                    # R2 modifier would otherwise disappear from the obligation.
                    raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            selected.setdefault(group.public_id, []).append((group, option))
            normalized.append(
                {
                    "group_public_id": str(group.public_id),
                    "option_public_id": str(option.public_id),
                    "quantity": str(option.default_quantity),
                    "instruction_snapshot": option.preparation_instruction,
                }
            )
        for cfg in configs:
            choices = selected.get(cfg.group.public_id, [])
            if cfg.group.selection_mode.value == "quantity":
                count = sum(int(option.default_quantity) for _, option in choices)
            else:
                count = len(choices)
            if count < cfg.group.minimum_selections or count > cfg.group.maximum_selections:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            if cfg.group.selection_mode.value == "single" and len(choices) > 1:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        return tuple(sorted(normalized, key=lambda x: (x["group_public_id"], x["option_public_id"])))

    def resolve_fixed_fee_line(
        self,
        *,
        scope: TrustedCheckoutScope,
        catalog_entry_ref: UUID,
        price_ref: UUID,
        at: datetime,
        currency: str,
    ) -> AuthoritativeLine:
        entry = self.so1_repo.catalog_entry(scope.tenant_id, catalog_entry_ref)
        price = self.so1_repo.price(scope.tenant_id, price_ref)
        if entry is None or price is None:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        catalog = self.so1_repo.catalog(scope.tenant_id, entry.catalog_public_id)
        if (
            catalog is None
            or not entry.enabled
            or not self._effective(entry, at)
            or not self._effective(catalog, at)
            or not self._effective(price, at)
            or price.target_type != entry.target_type
            or price.target_public_id != entry.target_public_id
            or price.currency != currency
            or (
                price.scope_type is ScopeType.LOCATION
                and int(price.scope_id or 0) != scope.location_id
            )
            or (
                price.scope_type is ScopeType.TENANT
                and int(price.scope_id or 0) != scope.tenant_id
            )
            or price.scope_type not in {ScopeType.LOCATION, ScopeType.TENANT}
        ):
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        return AuthoritativeLine(
            entry.public_id,
            entry.target_type.value,
            entry.target_public_id,
            price.public_id,
            Decimal("1"),
            Decimal(price.amount),
            price.currency,
            int(entry.row_version),
            int(price.row_version),
            (),
            (),
            "delivery_fee",
        )

    def open_session_if_required(
        self,
        *,
        scope: TrustedCheckoutScope,
        mode: Any,
        command_prefix: str,
        table_ref: UUID | None,
        party_ref: UUID | None,
        at: datetime,
    ) -> UUID | None:
        if not mode.requires_session:
            return None
        resources: tuple[UUID, ...] = ()
        if mode.requires_resource:
            if table_ref is None:
                raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
            resources = (table_ref,)
        result = self.r1.open_session(
            OpenSession(
                f"{command_prefix}:session",
                scope.tenant_id,
                mode.mode_code,
                1,
                at,
                party_public_id=party_ref,
                resource_public_ids=resources,
            )
        )
        return result.public_id

    def open_order(
        self,
        *,
        scope: TrustedCheckoutScope,
        mode_code: str,
        command_prefix: str,
        order_code: str,
        session_ref: UUID | None,
        party_ref: UUID | None,
        at: datetime,
    ):
        return self.r1.open_order(
            OpenOrder(
                f"{command_prefix}:order",
                scope.tenant_id,
                order_code,
                mode_code,
                "customer_channel",
                at,
                session_public_id=session_ref,
                party_public_id=party_ref,
            )
        )

    def add_line(
        self,
        *,
        scope: TrustedCheckoutScope,
        order: Any,
        line: AuthoritativeLine,
        command_key: str,
        at: datetime,
    ):
        target_type = (
            R1TargetType.ATOMIC_UNIT
            if line.target_type == TargetType.ATOMIC_UNIT.value
            else R1TargetType.OFFER
        )
        return self.r1.add_line(
            AddLine(
                command_key,
                scope.tenant_id,
                order.public_id,
                order.row_version,
                target_type,
                line.target_ref,
                line.price_ref,
                line.quantity,
                at,
            )
        )

    def set_line_modifiers(
        self,
        *,
        scope: TrustedCheckoutScope,
        order_line_public_id: UUID,
        selections: tuple[dict[str, Any], ...],
        command_key: str,
        at: datetime,
    ):
        if not selections:
            return None
        values = tuple(
            ModifierSelection(
                UUID(item["group_public_id"]),
                UUID(item["option_public_id"]),
                Decimal(item["quantity"]),
                Decimal("0"),
                None,
                item.get("instruction_snapshot"),
            )
            for item in selections
        )
        return self.r2.set_line_modifiers(
            SetLineModifiers(
                command_key,
                scope.tenant_id,
                order_line_public_id,
                values,
                at,
            )
        )

    def submit_order(self, *, scope: TrustedCheckoutScope, order: Any, command_key: str, at: datetime):
        return self.r1.submit_order(
            SubmitOrder(
                command_key,
                scope.tenant_id,
                order.public_id,
                order.row_version,
                at,
            )
        )

    def payment_request(self, *, scope: TrustedCheckoutScope, order_ref: UUID):
        return self.c3.create_payment_request(
            self.session,
            context=TrustedCheckoutContext(scope.tenant_id, scope.branch_id),
            order_public_id=order_ref,
        )
