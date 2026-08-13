# XA Frontend Experience Architecture Gate

XA freezes presentation-facing contracts; it does not implement a frontend. Its constitutional rule is:

> Kernel = truth; modules = capabilities; template = composition; merchant configuration = customization; frontend = presentation and operation.

## Boundary

The envelope carries resolved Platform Core context and references future module-owned projections. Identity and membership, structural context, semantics, operating configuration/time, and authorization are consumed only through the accepted PC1–PC5 public facades. XA owns no persistence and performs no writes.

Navigation visibility is presentation metadata, never an authorization grant. Every route, action, and search result carries a backend decision and explanation. Secret configuration is write-only. Workflow transitions, business date, entitlement, audit, Party identity, taxonomy identity, financial and reconciliation truth remain server authorities.

Dashboard cards are explicitly noncanonical projections with source, refresh, as-of, permission-filter, and state metadata. Work items and documents always identify their source authority. Offline commands are only queued when the server contract supplies idempotency, retry, and conflict metadata; server revalidation remains mandatory.

## Template readiness

The three examples prove the same neutral contract supports a platform-operator shell, a tenant merchant-administration shell, and a materially different tenant mobile/POS shell. Template references, terminology, regions, and module slots are inputs for a future PK composition engine. XA does not implement that engine.

## Installation and verification

Overlay the package at the repository root. In the approved activated Python 3.13.3 environment run:

```text
python scripts/verify_xa_frontend_experience_architecture.py
python -m pytest -q tests/contracts/test_xa_frontend_experience_architecture.py
```

The Windows gate `XBOS_XA_RUN_ACCEPTANCE.cmd` additionally runs all frozen Platform Core verifiers, focused XA contracts, full regression, compilation, and `git diff --check`. XA creates no Alembic revision and requires no database operation.
