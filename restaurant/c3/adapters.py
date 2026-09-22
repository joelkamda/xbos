from __future__ import annotations

from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine


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
    """The only C3 finance write path: accepted Neutral Finance request creation."""

    @staticmethod
    def create(session, command):
        return TransactionalPaymentIntentEngine.create_request(session, command)
