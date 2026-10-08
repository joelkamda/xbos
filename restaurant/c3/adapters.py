from __future__ import annotations

from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_intent_repository import PaymentIntentRepository
from core.integrations.xafpay.orchestration_service import XafPayOrchestrationService


class R1CheckoutAdapter:
    """Consumes accepted R1 public authority; no commercial reconstruction."""

    def __init__(self, authority):
        self.authority = authority

    def order(self, tenant_id, order_public_id):
        return self.authority.order(tenant_id, order_public_id)

    def obligation_handoff(self, tenant_id, order_public_id):
        return self.authority.obligation_handoff(tenant_id, order_public_id)


class StructuralScopeAdapter:
    def __init__(self, authority):
        self.authority = authority

    def resolve(self, *, tenant_id: int, branch_id: int):
        return self.authority.resolve(tenant_id=tenant_id, legacy_branch_id=branch_id)


class PaymentPolicyAdapter:
    def __init__(self, authority):
        self.authority = authority

    def resolve(self, *, tenant_id: int, as_of):
        return self.authority.resolve(
            tenant_id=tenant_id,
            key="wnd.payments.enabled_methods",
            as_of=as_of,
        )


class NeutralFinancePaymentRequestAdapter:
    """Accepted Neutral Finance command boundary for C3 request and C4 intent/attempt creation."""

    @staticmethod
    def create(session, command):
        return TransactionalPaymentIntentEngine.create_request(session, command)

    @staticmethod
    def find_request(session, *, tenant_id, public_id):
        return PaymentIntentRepository.find_request(
            session,
            tenant_id=tenant_id,
            public_id=public_id,
            lock=False,
        )

    @staticmethod
    def create_intent(session, command):
        return TransactionalPaymentIntentEngine.create_intent(session, command)

    @staticmethod
    def create_attempt(session, command):
        return TransactionalPaymentAttemptEngine.create(session, command)


class XafPayGatewayV2ExecutionAdapter:
    """C4 wrapper over the accepted Gateway V2 payment-create orchestration boundary."""

    @staticmethod
    def prepare(session, **kwargs):
        return XafPayOrchestrationService.prepare_payment_create(session, **kwargs)

    @staticmethod
    def create(request, *, service_credential, transport):
        return XafPayOrchestrationService.create_payment(
            request,
            service_credential=service_credential,
            transport=transport,
        )

    @staticmethod
    def record(session, command):
        return XafPayOrchestrationService.record_payment_create(session, command)
