# PC3 Semantic and Classification Authority

PC3 separates stable meaning from mutable labels and tree placement. A semantic identity is `namespace:code`; its definitions are effective-dated and fingerprinted. Labels are presentation metadata and may change without changing historical identity.

Existing `taxonomy_nodes` is adopted in place. Its IDs, tenant rows, parent hierarchy, `semantic_level`, `taxonomy_type`, and `atomic_unit_taxonomy` links remain intact. Legacy hints gain no canonical meaning automatically. Nodes may be linked explicitly to a taxonomy system and semantic concept.

Classification assignments retain the qualified code, semantic version, definition fingerprint, classification date, and optional taxonomy-node reference. Later label or tree changes therefore cannot reinterpret historical classifications.

Mapping sets preserve direction, type, effective period, and owner. Missing or ambiguous mappings fail closed. Impact analysis reports references without destructive cascades.

Atomic Units remain SO0 business objects. Frozen Finance catalogs and fingerprints remain Neutral Finance authority. PC3 provides no generic configuration or localization policy.
