# ADR 0018 — SO7 logical document, immutable version and evidence authority

## Decision

A document is a logical operational record, not a file path. Concrete content is represented by immutable document-version metadata. Evidence links bind a specific immutable version to a tenant-scoped business subject. Search is a derived projection and storage bytes remain adapter-owned.

## Why

Treating a path or URL as the document identity would make historical evidence mutable whenever content is replaced. Treating search as canonical would make index loss a truth-loss event. Treating uploaded invoices or receipts as financial truth would violate frozen Finance authority. The SO7 split keeps these concerns independent.

## Consequences

- New content creates a new version; historical versions remain identifiable and immutable.
- A current version is explicit on the logical document, but old versions remain retrievable.
- Evidence links preserve the exact version that supported an operational fact or decision.
- External subject resolvers preserve SO3–SO6 authority boundaries and tenant isolation without private-table coupling in SO7.
- PC3 classification and PC5 authorization are consumed, not reimplemented.
- Search can be rebuilt from canonical SO7 records.
- Actual object-storage implementation and content extraction/OCR remain downstream adapter/processor concerns.
- Finance, PC5 audit and source-domain truth remain unchanged.
