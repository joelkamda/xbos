# ADR 0011: SO0 authority, module and Finance boundaries

Status: Accepted candidate for operator gate

## Decision

Shared Operations is a modular operational layer downstream of frozen Platform Core and upstream of XA projections. SO modules consume public Platform Core facades and communicate with each other only through public contracts. Private repositories, persistence and SQL never cross module boundaries.

SO0 is constitutional only. No SO domain model, dynamic plugin engine, delivery runtime, pack engine, frontend or database object is created. SO0 uses a separate manifest so accepted PC0–PC6, Finance and XA integrity records remain unchanged.

SO1 prospectively owns Atomic Units. SO8 prospectively owns communications, delivery, retry and offline support. The earlier frozen SO0/SO9 labels are compatibility provenance within the Shared Operations program, not permission to rewrite frozen Platform Core.

## Consequences

- PC2 remains person/company identity authority while SO may own operational relationships.
- PC3 supplies semantic identity rather than SO free-form taxonomies.
- PC4 supplies configuration and business time; PC5 supplies authorization and audit.
- Operational evidence may enter Finance only through approved public contracts.
- Pack declarations are data hooks only; PK owns their lifecycle.
- XA metadata is supplied without UI or layout implementation.
