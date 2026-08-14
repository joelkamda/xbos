# SO4 Procurement and Supplier Operations

SO4 owns operational purchase requests, purchase orders, receipts and their traceable lifecycle. Supplier identity is PC2 Party; operational supplier participation is an active SO2 supplier/vendor relationship. Lines reuse SO1 Atomic Units and accepted stock receipts call the public SO3 receipt contract in the same transaction.

SO4 never makes a purchase order an AP liability and never turns a receipt into an expense, payable, journal, tax, payment or valuation fact. Legacy supplier/vendor strings and receipt references remain compatibility evidence until explicit source-specific mapping.

The minimal lifecycle is `draft -> submitted -> approved -> ordered -> partially_received/received -> closed`, with cancellation only before receipt. Approval consumes PC5 decisions. Retryable commands carry a tenant-scoped command key and exact request fingerprint. Over-receipt is forbidden unless the profile selects `allow_with_authorization` and the server authorizes the concrete attempt.

XA metadata is presentation-only. SO7 documents, SO8 communications, SO10 scheduling, SO6 general workflow and PK lifecycle are excluded.
