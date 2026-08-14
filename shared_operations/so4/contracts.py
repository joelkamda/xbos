"""Stable public contracts for neutral procurement operations."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ProcurementStatus(StrEnum):
    DRAFT="draft"; SUBMITTED="submitted"; APPROVED="approved"; ORDERED="ordered"
    PARTIALLY_RECEIVED="partially_received"; RECEIVED="received"; CANCELLED="cancelled"; CLOSED="closed"


class LineType(StrEnum):
    STOCK="stock"; SERVICE="service"


class OverReceiptPolicy(StrEnum):
    FORBID="forbid"; ALLOW_WITH_AUTHORIZATION="allow_with_authorization"


@dataclass(frozen=True)
class ProcurementLineInput:
    line_number:int; line_type:LineType; description:str; quantity:int
    atomic_unit_public_id:UUID|None=None; stock_location_public_id:UUID|None=None


@dataclass(frozen=True)
class PurchaseRequest:
    public_id:UUID; tenant_id:int; request_code:str; status:ProcurementStatus
    lines:tuple[ProcurementLineInput,...]; expected_by:datetime|None; row_version:int


@dataclass(frozen=True)
class PurchaseOrderLine:
    public_id:UUID; line_number:int; line_type:LineType; description:str
    atomic_unit_public_id:UUID|None; stock_location_public_id:UUID|None
    ordered_quantity:int; received_quantity:int
    @property
    def outstanding_quantity(self)->int: return max(0,self.ordered_quantity-self.received_quantity)


@dataclass(frozen=True)
class PurchaseOrder:
    public_id:UUID; tenant_id:int; order_code:str; supplier_party_public_id:UUID
    supplier_relationship_public_id:UUID; status:ProcurementStatus
    over_receipt_policy:OverReceiptPolicy; lines:tuple[PurchaseOrderLine,...]
    expected_by:datetime|None; row_version:int


@dataclass(frozen=True)
class ReceiptLineInput:
    order_line_public_id:UUID; quantity:int


@dataclass(frozen=True)
class ProcurementReceipt:
    public_id:UUID; tenant_id:int; purchase_order_public_id:UUID; receipt_code:str
    occurred_at:datetime; lines:tuple[ReceiptLineInput,...]; stock_movement_public_ids:tuple[UUID,...]


@dataclass(frozen=True)
class CreatePurchaseRequest:
    command_key:str; tenant_id:int; request_code:str; lines:tuple[ProcurementLineInput,...]
    expected_by:datetime|None=None; source_reference:str|None=None; document_reference:str|None=None


@dataclass(frozen=True)
class CreatePurchaseOrder:
    command_key:str; tenant_id:int; order_code:str; supplier_party_public_id:UUID
    supplier_relationship_public_id:UUID; lines:tuple[ProcurementLineInput,...]
    request_public_id:UUID|None=None; expected_by:datetime|None=None
    over_receipt_policy:OverReceiptPolicy=OverReceiptPolicy.FORBID
    approval_public_id:UUID|None=None; source_reference:str|None=None; document_reference:str|None=None


@dataclass(frozen=True)
class TransitionProcurement:
    command_key:str; tenant_id:int; resource_public_id:UUID; expected_version:int
    to_status:ProcurementStatus; reason_code:str; occurred_at:datetime; approval_public_id:UUID|None=None


@dataclass(frozen=True)
class ReceivePurchaseOrder:
    command_key:str; tenant_id:int; purchase_order_public_id:UUID; receipt_code:str
    lines:tuple[ReceiptLineInput,...]; occurred_at:datetime
    source_reference:str|None=None; document_reference:str|None=None; metadata:dict[str,Any]=field(default_factory=dict)
