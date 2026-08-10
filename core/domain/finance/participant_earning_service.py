"""Read-only participant earning position service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .participant_earning_repository import ParticipantEarningRepository


@dataclass(frozen=True)
class ParticipantEarningPosition:
    tenant_id: int
    beneficiary_party_id: UUID
    currency_code: str
    outstanding_payable: Decimal


class ParticipantEarningBalanceService:
    repository = ParticipantEarningRepository

    @classmethod
    def get(cls, session, *, tenant_id: int, beneficiary_party_id: UUID, currency_code: str):
        currency = str(currency_code).strip().upper()
        return ParticipantEarningPosition(tenant_id, UUID(str(beneficiary_party_id)), currency, cls.repository.beneficiary_balance(session, tenant_id=tenant_id, beneficiary_party_id=beneficiary_party_id, currency_code=currency))
