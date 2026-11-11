"""Unregistered D1 Local-First node authority migration design ? source only.

NOT an Alembic revision: expressly excluded from PC0 frozen inventory.
A future separately authorized schema admission must verify the existing
tenant and PC5 schema, integrity, backup/restore and least privilege.
No execution, grant, signing, or operative epoch promotion is provided.
"""

PROPOSED_TABLE = "xcomp_local_node_authority_epochs"
PROPOSED_FIELDS = (
    "tenant_id", "node_id", "epoch", "writer_scope",
    "activated_at", "expires_at", "fenced_at",
    "issuer_key_id", "verified_grant_digest", "created_by_pc5_id",
)
PROPOSED_CONSTRAINTS = (
    "tenant_id positive and valid tenant FK",
    "node_id immutable and uniquely enrolled under tenant",
    "epoch positive, strictly increasing on promotion",
    "only one unfenced canonical writer for (tenant_id, writer_scope)",
    "active expiry later than activated_at",
    "issuer key identity and signed grant digest not NULL",
    "no implicit grants to PUBLIC, application runtime or browser roles",
)
REQUIRED_PRECONDITIONS = (
    "Independent PostgreSQL 17 schema/role readback",
    "Isolated verified backup+restore rehearsal and rollback manifest",
    "Prospective PC0 migration lineage extension, not frozen-inventory edit",
    "Certified platform-issued offline node delegation",
    "Signed new-epoch custody and old-node fencing proof",
    "Source identity, tenant isolation and non-destructive migration review",
)
def proposed_schema_manifest() -> dict:
    """Return descriptive proposal only. Never executes database statements."""
    return {
        "table": PROPOSED_TABLE,
        "fields": PROPOSED_FIELDS,
        "constraints": PROPOSED_CONSTRAINTS,
        "preconditions": REQUIRED_PRECONDITIONS,
        "registered": False,
        "executable": False,
    }
