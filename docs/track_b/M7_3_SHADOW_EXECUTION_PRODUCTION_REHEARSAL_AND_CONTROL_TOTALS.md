# M7.3 — Shadow execution, production rehearsal, and control totals

M7.3 turns accepted M7.1/M7.2 mapping plans into deterministic, production-shaped
shadow cases. It compares exact canonical control totals without changing WND
writer routing or acquiring canonical financial authority.

The allowed execution environment is an isolated disposable rehearsal. A case
retains tenant, organization, source identity, source fingerprint, mapping-plan
fingerprint, expected totals, and its disposition. Withheld cases—especially
historical fulfillment records without reliable cost—cannot be executed.

Control totals cover commercial recognition, allowances, collections,
receivable opening and satisfaction, refunds, verified fulfillment cost, and
financial-document linkage. Comparisons preserve exact decimal values, report
variances rather than forcing balance, and are fingerprinted deterministically.

This package is schema-neutral. It does not execute production writes, reroute
legacy writers, establish dual-read compatibility, declare cutover readiness,
retire writers, or perform live migration. Those later support controls belong
to M7.4; R6 remains the owner of operational migration and production cutover.
