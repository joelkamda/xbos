# XBOS Neutral VN2-R1-C1 — Pack / Template Discovery Contract Freeze

**Authority:** `XBOS-NEUTRAL-VN2-R1-C1`, PCR, 2026-10-11. **Parent:** `XBOS-NEUTRAL-VN2-R1` / `BLOCKED_ACCEPTED`. **Purpose:** design and freeze an authenticated, neutral, tenant-scoped, read-only discovery projection. **Implementation:** **NOT AUTHORIZED** in C1.

Accepted backend: `78e5488c65d6955fb2e436cf2b3d9b19f0109f92` / tree `a1d03fec574b892263318899aa0ac73d42b6c51f`.
Accepted frontend: `1b0d4b4d5b8c1a7afdddbe4c0abc92df9a3d7419` / tree `339df9262e4c033260d75925a116f419c1c42cd4`.

## Frozen machine-readable contract

`contracts/platform/v1/vn2_pack_template_discovery_v1.json` freezes the request, authentication, scoping, response JSON Schema, complete leaf field provenance, status normalization, ordering, safe errors, cache law and future implementation boundary.

**Planned:** `GET /api/kernel/platform/v1/pack-template-discovery`. No request body, no query parameters, no caller-tenant, merchant or location overrides. The URL is a **future** route designation and is **not yet implemented**.

Successful response contains exactly `schema`, `tenant_ref`, `packs`, `templates`. `schema` is the literal `xbos.platform.pack-template-discovery.v1`; `tenant_ref` is the existing positive integer tenant ID derived **only from authenticated server browser context**, never the browser's tenant-code entry field.

### Authority and security

1. Reuse VN0 `browser-session.v1` access authority and existing `/kernel/auth/me` identity semantics. The future handler MUST independently validate the accepted browser access token and session, then load/compare identity, user, tenant and branch using the existing trusted server authority. The authentication result is a server assertion; do not trust client role/permission booleans, local tenant selections, or header values.
2. **Important pre-existing middleware hazard:** `core/middleware/tenant_middleware.py` and `core/middleware/branch_middleware.py` have existing header and development fallback behavior. Therefore a future discovery route cannot use fallback `request.state.tenant_id` or caller `X-Tenant-Code` / `X-Branch-Code` as pack-selection authority. Any route composition/reordering work that would affect PC0 must receive new PCR C2 architecture authorization.
3. The SQL-facing application projection receives a bound, validated `tenant_id` derived from the browser session. Both `pk_tenant_pack_installations` and `pk_tenant_template_bindings` use that same tenant ID in their left-join condition. A missing or inconsistent context is a safe error and never falls back to an arbitrary/default tenant.
4. This contract defines authenticated tenant-scoped discovery, **not** a new permission or role, and explicitly does **not** assert a separate pack entitlement/eligibility permission. PCR must separately approve any future new entitlement model.

### Accepted data-source map

| Response path | Canonical source |
|---|---|
| `tenant_ref` | Existing validated browser-access identity (`tenant_id`), reconciled with `AuthService.me` |
| `packs[].pack_code`, `owner_code`, `pack_kind` | `pk_packs`; PK0–PK3 ownership |
| `packs[].versions[].version`, `manifest_sha256`, `retention_required` | `pk_pack_versions`; safe immutable version metadata |
| `packs[].tenant_state.status` | Tenant-ID-scoped `pk_tenant_pack_installations.lifecycle_status`; uppercase status normalization or explicit `ABSENT` |
| `packs[].tenant_state.version` | `pk_tenant_pack_installations.pack_version_id → pk_pack_versions.pack_version`; only for existing state |
| `packs[].tenant_state.row_version` | `pk_tenant_pack_installations.row_version`; only for existing state |
| `templates[].template_code`, `owner_code` | `pk_templates`; PK456 ownership |
| `templates[].versions[].version`, `template_sha256`, `industry_semantic_ref`, `operating_model_semantic_ref` | `pk_template_versions` authoritative persisted immutable metadata |
| `templates[].versions[].requirements[]` | `pk_template_pack_requirements(pack_code,pack_version,requirement_kind)` |
| `templates[].tenant_state.status` | Tenant-ID-scoped `pk_tenant_template_bindings` row presence → `APPLIED` or `ABSENT` |
| `templates[].tenant_state.version` | Bound `pk_template_versions.template_version`; only when applied |
| `templates[].tenant_state.row_version`, `selected_optional_packs` | Existing `pk_tenant_template_bindings` fields; only when applied |

Every individual response leaf is also inventoried in the machine-readable `field_provenance` map. Underlying tables were verified in accepted migrations `alembic_neutral/sql/pk0123_pack_manifest_lifecycle_up.sql` and `alembic_neutral/sql/pk456_pack_conformance_templates_up.sql`. Corresponding accepted domain owners remain `PackAuthority` / `SQLPackRepository` and `PK456Authority` / `SQLPK456Repository`. Direct frontend SQL and private repository access are prohibited.

**Catalog != entitlement.** The frozen projection can show registry identity/version to a verified tenant without declaring those packs available, enabled, eligible or entitled for the tenant. `ABSENT` means there is no tenant installation/binding record, **not** an eligibility decision. There is no `eligible`, `entitled`, or `available_to_tenant` field.

**Pack selection:** The domain's tenant installation status is the only persisted pack-state fact: `ABSENT`, `STAGED`, `INSTALLED`, `ACTIVE`, `DISABLED`, or `REMOVED`. It is not reinterpreted as client selection.

**Template selection:** The only persisted template-state fact is an existing binding: `APPLIED`; otherwise `ABSENT`. A browser click may represent *volatile selection intent* in later VN2 but does not apply, provision, enable or upgrade anything.

**Minimal metadata:** Display safe IDs, owner, kinds, immutable version/hash, safe semantic references, and exact pack requirements. Exclude raw manifests, template_json, defaults/overrides, terminology, XA declarations, connector secret references, credentials, payloads and unproven icons/descriptions. Industry semantics may occur as server-stored template version data, **never a frontend default**.

### Deterministic order and completeness

- Packs: `pack_code` ascending; pack versions: stored `pack_version` ascending.
- Templates: `template_code` ascending; template versions: stored `template_version` ascending.
- Template requirements: `pack_code`, `requirement_kind`, then `pack_version` ascending.
- Applied template optional pack codes ascending.
- Ordering uses explicitly contracted **case-sensitive ordinal UTF-8 byte comparison**, not incidental DB ordering or an assumed semantic-version comparator. Implementer must specify the corresponding SQL collation/order and validate round-trip order.
- If no records exist, return `packs: []`, `templates: []`; do not synthesize a pack, template, business vertical, default or selection.
- On data read failure, return a safe error; never silently reinterpret incomplete data as a successful empty catalog.

### Fail-closed errors and caching

Error envelope: `{"error":{"code":"UNAUTHENTICATED"}}` (401), `TRUST_CONTEXT_UNAVAILABLE` (403), `TENANT_CONTEXT_UNAVAILABLE` (403), `DISCOVERY_UNAVAILABLE` (503). No raw SQL/stack/secret/identity in errors. Never convert denied, missing context or back-end failure into an authenticated empty response.

Successful response policy: `Cache-Control: private, no-store` with `Vary: Authorization`. Server truth remains authoritative even if the UI temporarily keeps a displayed projection. No persistent client authority cache; no stale override.

### Future C2 composition (unimplemented)

Future authenticated HTTP adapter may compose read-only PK0123 + PK456 data behind the existing kernel. It must use exact explicit SELECT projections, bound tenant ID, no `FOR UPDATE`, no INSERT/UPDATE/DELETE, no command key, no activation or template-apply path; it may not import private persistence into frontend. It must separately prove PC0 dependency legality or obtain explicit PCR C2 admission for any new architecture edge. No future implementation authority is implied by C1 contract freeze.

## C1 invariants and evidence

- C1 **does not** create an HTTP route, modify `startup.py`, `core/api/kernel_router.py`, middleware, `pack_platform/`, SQL repository, settings, database, schema or migrations.
- Only one new `contracts/platform/v1` JSON contract, this documentation, and targeted `tests/contracts` test module are allowed.
- Existing PC0/PC6 release/architecture fingerprints remain unchanged; if monitored integrity fails, stop for PCR.
- No frontend source changes, push, merge, tag, deployment, data writes, tenant mutation or financial effects.
- Targeted contract conformance covers source provenance, input scoping, no entitlement inference, absence/denial cases, no secret material, exact status/field allowlist, deterministic ordering, and architecture firewall.
- Parent `XBOS-NEUTRAL-VN2-R1=BLOCKED_ACCEPTED` remains historical. VN2-R1-C1 passing candidate is not VN2 frontend implementation, and C2 requires a separate PCR release.

## Regression audit and accepted-parent replay

- New C1 contract tests: **20/20 PASS** (`tests/contracts/test_vn2_c1_discovery_contract.py`).
- Accepted PK0123 suite: **4/4 PASS** (`tests/contracts/test_pk0123_pack_manifest_lifecycle_extensions.py`).
- Accepted PK456 suite: **7/7 PASS** (`tests/contracts/test_pk456_pack_conformance_templates.py`).
- Accepted PC0 suite: **21/21 PASS**; accepted PC6 suite: **18/18 PASS**.
- Broader PK aggregate suite: **10 PASS / 2 FAIL**, with `PC8_SUCCESSOR_DESCENDANT_HASH_MISMATCH=core/platform/architecture_contract.py` in the historical PC8 successor verifier. The same **10 PASS / 2 FAIL**, same source hash and error, were independently reproduced in a temporary detached worktree at accepted parent `78e5488c65d6955fb2e436cf2b3d9b19f0109f92`. That worktree was removed after replay.
- These two failures are **inherited** and unrelated to C1's additive contract, doc, and tests. They are **not** reported as passing. Under C1 source-firewall authority, the team must **not** edit `core/platform/architecture_contract.py`, PC8 release evidence, PK aggregate tests, or the frozen successor chain to mask the mismatch. PCR must adjudicate whether this historical, accepted-parent aggregate assertion is outside C1's regression acceptance law.

**No HTTP implementation, DB access or mutation was performed by C1.** The contract is a frozen candidate for future independently authorized C2 materialization.
