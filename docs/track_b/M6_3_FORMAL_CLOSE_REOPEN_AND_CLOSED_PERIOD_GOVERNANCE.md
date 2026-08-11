# M6.3 Formal Close, Reopen, and Closed-Period Governance

M6.3 makes reconciliation-window closure an enforceable financial control. It does not replace M2.4 accounting periods: an accounting period governs journal posting, while a reconciliation close governs the operational account, series, and window. The controls are separate but coordinated.

## Authority

- A close targets the current, ready M6.2 window revision and an open or separately reopened covering accounting period.
- The first window may close directly; every successor requires its predecessor's latest governance transition to be `close`.
- `balanced` requires zero variance. Non-zero variance requires `explained_variance` or `approved_exception` plus immutable evidence.
- A reopen appends a transition linked to the latest close. It requires a tenant-scoped approver, reason, approval time, and evidence.
- Re-closing after a reopen targets the latest reconciliation revision and appends another transition. Earlier close/reopen facts remain visible.

## Closed-window protection

Database triggers reject new operational balance facts and financial events inside a closed window. They also reject intersecting correction cascades and direct reconciliation-revision inserts. This makes closure authoritative for application, repository, and direct-SQL writers.

An accounting period in `closed` state blocks both reconciliation close and reopen. Accounting-period reopening remains a separate M2.4 action; M6.3 never changes that state.

## Deferred

Bank, A/R, and A/P reconciliation workflows, general supporting-document management, reconciliation reports, and the M6 freeze belong to M6.4–M6.5.
