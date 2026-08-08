# XBOS Track B — M2.5 Financial Dimensions and Posting Context

## Status

Approved implementation candidate, anchored to commit `c6e3b6d` and migration
`m24_balanced_posting_006`.

## Purpose

M2.5 adds controlled analytical dimensions to canonical journal lines while
preserving the neutrality of the financial kernel. The kernel does not define
restaurant, hotel, retail, healthcare or payment-provider vocabulary. Tenants
and later industry packs may configure dimension types, values and posting
policies without changing canonical event or journal semantics.

Examples include channel, cost center, department, project, location, business
line and industry context. They are examples, not reserved kernel fields.

## Authority boundaries

- `organization_units` remains the structural legal and operational scope.
- `financial_dimension_types` defines tenant-controlled analytical axes.
- `financial_dimension_values` defines effective-dated controlled members.
- `posting_dimension_policies` explicitly permits, requires, forbids or
  defaults one dimension for one posting profile and account role.
- `journal_lines.dimension_snapshot.financial_dimensions` is the immutable
  resolved record used for reporting and explanation.
- Industry packs may seed configuration but never become financial authority.

This prevents a branch, kitchen, menu, room, shelf, payment provider or any
other industry concept from being hard-coded into the journal engine.

## Posting-context shape

Global values apply to every line that has an effective policy:

```json
{
  "dimension_values": {
    "channel": "whatsapp"
  }
}
```

Account-role values override global values for that journal line:

```json
{
  "dimension_values": {
    "channel": "whatsapp"
  },
  "account_role_dimension_values": {
    "classified_revenue": {
      "department": "retail",
      "cost_center": "sales"
    }
  }
}
```

Both keys map controlled codes to controlled value codes. Numeric database IDs
are not accepted from callers.

## Fail-closed policy

For every posting line, M2.5 resolves policies using tenant, legal entity,
posting profile, account role and event business date. Exact profile and role
policies outrank wildcard policies. Equal-specificity matches are rejected.

- `required`: a context value or configured default must resolve.
- `optional`: a supplied value is validated; an optional default may apply.
- `forbidden`: any supplied value is rejected.
- no effective policy: a supplied dimension is rejected.
- inactive, expired, cross-tenant or ambiguous values are rejected.
- an account-role override for a role absent from the journal is rejected.

An M2.4 posting with no dimension configuration and no dimension context still
posts with an empty `financial_dimensions` object. This preserves additive
compatibility while preventing silent loss once dimensions are supplied.

## Immutable snapshots and corrections

Each posted line records the resolved type ID, value ID, value code, display
name and whether the value came from posting context or a policy default.
Posted-line immutability is inherited from M2.4.

Inverse-original correction and reversal profiles do not re-resolve current
dimension policy. They copy the original line snapshot exactly. A caller
cannot reclassify such a historical fact by putting new dimensions on the
inverse command; such input is rejected. Dedicated template corrections, such
as commercial returns, continue to use their own approved posting profile and
effective dimension policy because their line roles intentionally differ from
the original journal.

## Configuration history

Dimension configuration rows cannot be deleted. Administrators end-date or
deactivate configuration and add a new effective row where policy evolution is
needed. This keeps journal explanations reproducible.

## Migration

Linear revision:

```text
m24_balanced_posting_006
    -> m25_financial_dimensions_007
```

The migration adds three empty configuration tables and one JSON-shape
constraint. It creates no tenant dimension data, financial event, outbox
message or journal.

## Verification gate

The disposable verifier proves:

- linear upgrade, downgrade and re-upgrade;
- global dimension selection and account-role override;
- required default application;
- missing, forbidden and unconfigured dimension rejection;
- tenant isolation;
- exact correction snapshot inheritance;
- posted snapshot immutability;
- atomic event, idempotency, outbox and journal counts.

## Deferred

M2.5 does not add uncontrolled free-form values, allocation splits,
statistical dimensions, cross-tenant sharing, configuration UI, industry-pack
seed data, WND writer cutover or outbox dispatch.
