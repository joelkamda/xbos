# SO7 — Documents, Files, Evidence and Search

SO7 establishes the neutral Shared Operations authority for logical documents, immutable file-version metadata, evidence linkage, and tenant-safe derived document search.

## Authority boundaries

- PC3 remains semantic/classification authority. SO7 stores resolved classification-code snapshots; it does not create a second semantic taxonomy.
- PC5 remains identity, authorization, protected-action and audit authority. SO7 permission checks are server-side and SO7 does not write PC5 audit/security truth.
- SO6 remains workflow/task/operational-approval authority. SO7 evidence links may reference SO6 subjects but cannot change workflow state or approval outcome.
- Storage bytes remain behind adapters. SO7 persists provider-neutral locators, content metadata and SHA-256 identity; it does not hard-wire S3, Azure, local disk or database BLOB storage.
- Search is a derived projection over SO7 canonical records. Search results are discovery aids, never source of truth.
- Finance remains unchanged. An uploaded invoice, receipt, statement or contract is evidence only and does not create obligations, journals, payments, settlements, revenue, expense or valuation truth.

## Canonical model

`so7_documents` is the logical document identity. A logical document has tenant scope, title, PC3-resolved classification snapshot, lifecycle, metadata, current version number and optimistic row version.

`so7_document_versions` is append-only content metadata. Every version has its own public identity, monotonically increasing document version number, file name, MIME type, byte length, SHA-256, storage provider/key and optional creator reference. Historical version rows cannot be updated or deleted.

`so7_evidence_links` states why a specific immutable document version is relevant to a business subject. The subject is referenced through a neutral authority/reference pair and validated through an external public resolver. Ending a link preserves the row and records its end time/reason.

`so7_document_search_projection` is a rebuildable SQL view over canonical document and current-version metadata. It owns no independent truth.

## Lifecycle and mutation rules

Documents support `active`, `archived`, and terminal `withdrawn` states. New file versions require an active document. Evidence may not be newly linked to withdrawn documents. File versions are append-only. Evidence links are explicitly ended rather than silently deleted.

All mutating public commands use an SO7-local tenant-qualified command ledger with exact request fingerprints. Same key plus exact command content is replay; same key plus changed content is `SO7_COMMAND_CONFLICT`.

Document version registration serializes on the canonical document row using scoped PostgreSQL row locking and optimistic row versions. Evidence creation serializes on the document row and binds a specific version. Tenant-qualified foreign keys prevent cross-tenant evidence/version binding.

## Legacy adoption

SO7 does not bulk reinterpret existing WND or Finance evidence. Existing Finance hashes/references and PC5 audit evidence remain in their frozen authorities. SO4 document-reference strings, SO6 evidence-reference strings, receipt artifacts and other legacy locators are mapping/bridge candidates only when explicit source evidence exists. Free-text writers retire later through source-specific convergence and R6 production cutover.

## Neutrality and later milestones

SO7 supports materially different document vocabularies such as field-service inspection evidence and clinical controlled records without changing source. SO8 later owns communications/delivery, SO9 later owns reporting/automation, SO10 later owns scheduling/reservations, and PK/PA later provide pack/template composition. No frontend implementation is included in SO7.
