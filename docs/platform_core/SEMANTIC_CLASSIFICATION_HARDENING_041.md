# Pre-R0 Semantic Classification Hardening 041

## Purpose

This checkpoint completes the global-capable semantic-classification infrastructure required before Restaurant becomes the first industry consumer. It is a bounded descendant of the frozen PC3 semantic authority; it does not redesign PC3, Shared Operations, Packs/Templates, Platform Administration, Finance, Atomic Units, WND, or Restaurant.

The governing model is:

> one reusable physical hierarchy engine, many independent logical taxonomy systems, arbitrary depth, many-to-many classification of native XBOS objects, and explicit mappings between independent semantic systems.

`domain`, `category`, `subcategory`, `sector`, `family`, and similar words are presentation vocabulary for hierarchy depth. They are not physical schema levels.

## Why a descendant layer is required

Frozen PC3 correctly separated stable semantic identity from labels and tree placement, adopted the WND-era `taxonomy_nodes` in place, and added namespaces, versions, mappings and assignments. The global design review proved three things that cannot be represented safely by the legacy tenant tree alone:

1. global and pack-contributed nodes must exist without a fake tenant;
2. hierarchy placement must remain historically explainable when a node moves;
3. tenant customization must be a delta/overlay over inherited global/pack structure rather than a cloned tree.

The legacy `taxonomy_nodes`, `atomic_unit_taxonomy`, and frozen PC3 `semantic_commands` remain untouched. This migration adds a governed global-capable placement layer and keeps those structures as compatibility bridges until explicit WND/pack migration work.

## Authority boundaries

- PC3 remains semantic identity, taxonomy/classification and semantic-mapping authority.
- PC1 remains Tenant/Organization/Legal Entity/Location authority.
- PC2 remains Party authority.
- PC4 remains configuration/localization/business-time authority.
- PC5 remains identity/security/audit authority.
- SO1/SO0 remains Atomic Unit/Catalog/Offer/Price authority.
- Other Shared Operations modules remain their native operational authorities.
- PK remains Pack/Template composition and tenant-template binding authority.
- PA remains merchant lifecycle/administration authority.
- Neutral Finance remains the sole financial-truth authority.

Classification references those authorities; it never acquires their write authority.

## Physical model

### `taxonomy_systems`

Existing PC3 table. Each row is a logical taxonomy system such as `commerce`, `finance`, `party`, `industry`, or `measurement_units`.

### `semantic_taxonomy_nodes`

Stable placement identities within one taxonomy system. A node references exactly one semantic concept. Nodes may be:

- global/kernel/finance/pack/external: `tenant_id IS NULL`;
- tenant-local extension: `tenant_id=<tenant>` and the semantic concept must be owned by that same tenant namespace.

A tenant-local node may descend from a global node. A global node may never descend from tenant-local structure. Template application may select or classify semantics, but a template does not author semantic taxonomy placement.

### `semantic_taxonomy_placements`

Effective-dated, append-protected parent/sort history. A node has one effective parent at a time. The model is tree/forest, not DAG-by-default. Re-parenting closes the prior placement and appends the next version; prior placement is not overwritten.

### `tenant_taxonomy_overlays`

Effective-dated tenant deltas over inherited nodes. A tenant can rename, reorder, suppress, or re-parent within its effective view without mutating inherited global/pack nodes. Only deltas are persisted; an unchanged inherited tree generates no tenant copy. Database guards reject both direct tree cycles and effective cycles created by the interaction of tenant parent overrides with global/pack placement changes.
Parent override is explicit: `has_parent_override=false` means inherit the base parent, while `has_parent_override=true` may identify another visible parent or use `NULL` to make the node an effective tenant root. This avoids overloading `NULL` with two meanings.

### `semantic_classification_governance`

Governance sidecar for frozen PC3 `classification_assignments`. It adds semantic-taxonomy-node placement, source/provenance, assignment mode and effective lifecycle while preserving the existing PC3 semantic-version snapshot.

### `semantic_classification_commands`

Tenant-qualified idempotency for descendant semantic-classification commands. `(tenant_id, command_key)` uses `NULLS NOT DISTINCT`, so the same caller key may be used independently by different tenants while global commands remain globally idempotent. Frozen PC3 `semantic_commands` is unchanged.

## Composition and visibility

Pack/template applicability is supplied as composition context (`active_sources`) to the semantic read model. This avoids creating a second template authority beside PK.

Example:

```text
XBOS global nodes
+
Restaurant pack source = restaurant.core@1.0.0
+
PK/PA effective merchant composition
+
WND tenant overlay
=
WND effective semantic taxonomy
```

A Restaurant pack may contribute a node whose concept is pack-owned inside the global `commerce` system. A payments-only tenant without that pack source does not see the pack-contributed node. Pack/template-sourced classifications and overlays are also composition-filtered, so inactive sources cannot leak into effective tenant matrix or hierarchy views. The underlying global system remains the same.

## Classification target validation

The semantic layer never executes arbitrary dynamic SQL from `subject_type`/`subject_key`. Runtime composition registers each supported target type with:

- stable target type code;
- native authority owner;
- scope law;
- reference format;
- owning-authority validator.

This preserves extensibility without turning `classification_assignments` into an unsafe polymorphic mega-FK.

Frozen PC3 `classification_assignments` remains intentionally tenant-contextual. Tenant-owned objects (and the tenant itself in its own context) use this governed assignment path. Global objects such as PK packs/templates keep their native semantic-reference contracts; this checkpoint does not invent a fake platform tenant merely to force every object through one table.

## Atomic Unit boundary

This checkpoint freezes only the separation, not AU redesign:

```text
classification          AU -> semantic taxonomy
family / variant        concrete identity specialization
commercial composition  SO1 Offer -> components
operational composition recipe/BOM/assembly -> inputs
catalog / price          SO1
inventory                SO3
procurement              SO4
Finance                  actual economic/accounting truth
```

`unit_type` and deeper AU-family design remain later work.

## Read contracts

The authority exposes five backend read lenses:

1. **Hierarchy** — effective tree/forest for a system, tenant and composition context.
2. **Object** — what XBOS believes a selected native object is, with semantic path and provenance.
3. **Matrix** — selected objects by selected taxonomy systems.
4. **Graph** — local parent/children and explicit semantic mappings around a selected node.
5. **Health** — structural/provenance/composition issues with remediation guidance.

Frontend F may render these views but does not infer semantic truth.

## Global registry

`contracts/platform/v1/sc41_global_taxonomy_registry.json` freezes the vetted v0.1 candidate registry of 40 global taxonomy systems and their first-depth domain vocabulary. It is a constitutional seed registry, not a migration that bulk-inserts speculative trees. New namespaced systems remain legal without schema change when they answer a durable independent classification question.

## Historical guarantee

Exact governed placement history begins at this hardening layer. Earlier WND/legacy hierarchy history cannot be reconstructed if it was never recorded; later R5/R6 migration must preserve that fact rather than invent historical paths.

## Acceptance

The authoritative gate proves:

- exact PA6 predecessor and single descendant head;
- additive PC3-descendant hardening in new files; frozen predecessor PC3/SO1 files and PK/PA/Finance authority/business implementation bytes are not edited;
- PC0 inventory/release metadata and descendant cumulative release manifests are refreshed only to authorize and fingerprint the new PC3-owned migration artifacts; historical PC1-PC5 release manifests are not rewritten;
- global taxonomy nodes and pack contributions without fake tenants;
- tenant extension isolation;
- tenant overlays without inherited-node mutation;
- tenant-qualified command replay;
- historical path before and after re-parenting;
- Atomic Unit classification to a global semantic node using owning-authority validation;
- Restaurant-pack composition and a materially different payments-only tenant on the same infrastructure;
- hierarchy/object/matrix/graph/health reads;
- downgrade/re-upgrade;
- controlled `xbos_track_b_dev` adoption from exact predecessor or read-only verification at accepted head;
- full repository regression.
