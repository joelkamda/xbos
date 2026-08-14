# ADR 0017 — SO6 operational workflow is separate from PC5 security approval

## Decision

SO6 owns generalized operational workflow, tasks and business-operational approvals. PC5 remains the sole authority for identity, permission, authorization, protected-action approval, maker/checker and security audit.

An SO6 approval records that an operational business step was approved or rejected. It does not grant a permission and cannot bypass a PC5 authorization denial. SO6 invokes server-side authorization before mutations and stores no security role or protected-action approval.

Task assignees and operational approvers reference SO5 Resource identity. This reference conveys work ownership only; it grants no authentication or authorization rights.

SO6 stores due dates and evidence references but does not implement scheduling (SO10), files/documents (SO7), communications (SO8), or reporting/automation (SO9).

## Consequence

Shared modules and future packs can compose operational workflows without introducing another authorization engine, another resource identity, or financial semantics.
