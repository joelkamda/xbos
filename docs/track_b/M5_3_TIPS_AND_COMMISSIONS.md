# M5.3 — Tips and Commissions

M5.3 groups tips and commissions behind one participant-earning boundary. It adds no migration and keeps `m46_provider_financials_015` as the single canonical head.

## Tip authority

A tip must declare whether it belongs to a staff beneficiary or is tenant income. Staff-beneficiary tips post to the tip liability profile and atomically create an equal `expense_payable` for the named beneficiary. Tenant-income tips post to the approved income profile and are forbidden from creating a participant payable. Neither path fabricates payment-settlement evidence.

## Commission authority

A commission is an `EXPENSE_RECOGNIZED` fact using the existing expense-accrual profile and an equal beneficiary payable. Percentage commissions must exactly equal basis amount multiplied by rate divided by 100. Fixed commissions require the declared basis amount to equal the recognized amount. The basis, rate, commission code, and beneficiary are preserved in immutable event metadata.

## Transaction and scope controls

The engine validates source kind, tenant, organization, beneficiary, amount, currency, and recognition date before writing. The canonical event, outbox message, balanced journal, and payable share one savepoint. Any failure rolls back the complete earning command. Existing M2 and M3 idempotency authorities govern replay and conflict behavior.

## Acceptance

The disposable rehearsal proves staff and tenant tip policy, fixed and percentage commissions, beneficiary balances, source and tenant isolation, replay, conflict rejection, balanced posting, atomic rollback, unchanged canonical head, and a clean development database. Full regression remains mandatory.
