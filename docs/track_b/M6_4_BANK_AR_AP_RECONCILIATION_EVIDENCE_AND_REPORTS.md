# M6.4 — Bank, A/R, A/P Reconciliation, Evidence and Reports

M6.4 adds one neutral reconciliation-control primitive. It records an immutable comparison of canonical XBOS position against independently observed control evidence, explains variance, and produces a deterministic report. It does not create or edit financial truth.

Bank controls derive expected position from M6 operational-account anchors and canonical financial events and bind to an exact M6.2 reconciliation window revision. A/R and A/P controls derive their positions from M3 obligations, allocations, and reversals. Evidence is stored as immutable references and hashes; files remain the responsibility of future shared document infrastructure.

Each control identity has an append-only revision chain. Replay of the same idempotency command returns the original result; changed content under the same identity fails closed. Direct updates and deletes of controls, explanations, and evidence are rejected by PostgreSQL triggers.

Reports are deterministic read models. They expose opening, increases, decreases, adjustments, closing canonical position, external control position, explained amount, unexplained variance, status, evidence, and semantic/report fingerprints.

M6.3 close authority remains separate and authoritative. A bank reconciliation captures the governed window revision and close state visible when recorded; it neither closes nor reopens the window. Accounting-period governance also remains separate but coordinated.

Excluded: generic file storage, OCR, bank feeds, country/provider-specific logic, frontend screens, M6 freeze, M7 migration, and M8 hardening.
