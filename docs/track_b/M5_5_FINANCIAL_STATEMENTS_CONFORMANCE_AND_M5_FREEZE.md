# M5.5 Financial Statements, Lifecycle Conformance, and M5 Freeze

M5.5 closes Track B M5 without changing the canonical schema head. It adds deterministic customer and supplier statement projections, freezes semantic fingerprints for M5.0-M5.5, and aggregates every M5 disposable rehearsal into one release gate.

Statements are read models over immutable obligations, allocations, and reversals. They are tenant scoped, optionally organization scoped, currency specific, bounded by an inclusive business-date period, and evaluated at a timezone-aware `as_of`. Opening balance is derived from facts before the period; period obligations are debits, active allocations are credits, and closing balance is opening plus debits less credits. Stable ordering and a semantic SHA-256 make identical inputs reproducible.

The exit gate verifies the M2, M3, M4, and M5 manifests, the unchanged `m46_provider_financials_015` head, the empty development database, all M5.0-M5.4 disposable capability rehearsals, statement invariants, tenant isolation, the full regression suite, and clean source scope. No migration, WND writer switch, public route, development financial event, or outbox dispatch belongs in M5.5.
