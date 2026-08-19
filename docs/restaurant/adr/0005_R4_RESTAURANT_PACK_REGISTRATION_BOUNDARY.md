# ADR 0005 — R4 Restaurant Pack Registration Boundary

**Status:** Accepted when `R4_SINGLE_GATE=PASS`.

## Decision

Represent Restaurant as immutable PK industry pack `industry.restaurant@1.0.0`. R4 produces PK public registration and certification commands and may persist only the global pack-version/certification evidence through PK repositories.

## Authority law

- PK owns pack registry, lifecycle and certification.
- PC3/SC41 owns semantic identity and taxonomy placement.
- PC4 owns effective configuration.
- PC5 owns permission truth.
- SO authorities and Neutral Finance remain unchanged.
- XA receives composition metadata only.
- R4 installs or activates no tenant pack and registers no template.

## Consequence

R5 can prove Restaurant templates and WND composition without embedding WND assumptions into R0-R4 or granting Restaurant duplicate authority.
