# M6.2 — Reconciliation Windows, Continuity, and Correction Cascades

M6.2 adds neutral, shift-aligned reconciliation windows without creating another balance authority. Expected balances always come from the accepted M6.0 projection; movements remain canonical M6.1 financial events.

## Calendar and shift attribution

An immutable versioned policy declares an IANA timezone, the local business-day boundary, and ordered shift boundaries. Times before the business-day boundary belong to the preceding business date. No WND name or 6 p.m. rule is embedded: a tenant can configure those values in its own policy later.

## Strict continuity

Each reconciliation-enabled leaf operational account has at most one series. Its first window must begin at the series start. Every later window must name the latest predecessor and begin exactly where that predecessor ended. Windows are exactly one configured shift interval, so overlapping and skipped middle windows fail closed in both the engine and database trigger.

## Revisions and cascades

A window definition is immutable. Its initial explanatory snapshot is revision one. When an append-only financial correction or later actual observation changes an earlier projection, a governed cascade recomputes the affected window and every successor through M6.0, then appends only changed revisions. Earlier revisions and later actual-observation references remain visible. Financial events, transfers, anchors, and observations are never rewritten.

M6.2 records readiness (`awaiting_actual` or `ready`) only. Formal close, approval, closed-period protection, reopen, bank/A/R/A/P workflows, documents, and reports remain M6.3–M6.4.
