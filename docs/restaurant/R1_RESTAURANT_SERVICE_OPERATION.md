# R1 — Restaurant Service Operation

R1 is the first runtime Restaurant-pack checkpoint. It implements configurable service modes, SO5-backed dining/table profiles, service sessions, operational orders, waiter/cashier/server attribution, tabs/checks, exact split partitions, and deterministic order-to-Finance handoff.

WND is evidence, not the Restaurant standard. Tables are optional; the same source must support quick service, takeaway/delivery, bars, casual/fine dining, cafeterias and cloud kitchens.

R1 does not own SO1 catalog/pricing, SO3 stock, SO5 resource identity, SO10 reservations, PC2/PC5 people/identity, or Neutral Finance. Order-line price snapshots preserve historical commercial intent only. `obligation_handoff()` returns a deterministic source payload with `creates_financial_truth=false`; only Finance commands may create amounts owed, receivables, payments, settlement, journals or reconciliation truth.

R2 adds menu/fulfillment/preparation/recipe semantics. R3 adds Restaurant financial mappings without new Finance authority. R4 registers the pack, R5 proves WND configuration, and R6 owns migration/cutover.
