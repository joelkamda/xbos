# SO5 Resources and Operational Assignment

SO5 establishes neutral operational resource identity and assignment without redefining Party, authentication, structure, workflow, scheduling or Finance.

## Authority

- PC2 Party answers who a person is.
- PC5 Identity answers who can authenticate and what security policy permits.
- PC1 answers organizational/location context.
- SO5 answers what operational resource exists and how it is assigned.
- SO6 later owns generalized task/workflow execution.
- SO10 later owns calendar scheduling, appointments and reservations.
- Neutral Finance remains unchanged.

A Resource is never a User, Party, authorization role, account or financial asset. Person-backed resources explicitly reference Party. Non-person resources require no fake Party. Optional Identity association requires active membership in the same tenant and grants no permission.

Assignments carry operational capability and effective period. They do not grant PC5 authorization. Exclusive resources reject overlapping active assignments transactionally; multi-assignment resources may overlap. History is append-only and ending an assignment preserves the original assignment record.

Legacy users, branch references and staff strings are mapped or bridged only with explicit evidence. Historical commissions, payroll and accounting evidence remain untouched.
