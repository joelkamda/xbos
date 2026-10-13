"""Read-only, server-tenant-bound PK0123/PK456 discovery projection.

The caller must validate the browser session before passing tenant_id.
No ORM writes, row locks, private manifests, templates, or credentials.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def _rows(db: Session, sql: str, tenant_id: int | None = None) -> list[dict]:
    params = {} if tenant_id is None else {"tenant_id": tenant_id}
    return [dict(row) for row in db.execute(text(sql), params).mappings().all()]


def _key(value: str) -> bytes:
    return value.encode("utf-8")


def read_discovery(db: Session, tenant_id: int) -> dict:
    """Explicit SQL column allowlists; no caller-controlled identifiers or predicates."""
    if type(tenant_id) is not int or tenant_id < 1:
        raise ValueError("UNTRUSTED_TENANT")

    packs_by_id: dict[int, dict] = {}
    for row in _rows(db, """
        SELECT p.id AS pack_id, p.pack_code, p.owner_code, p.pack_kind,
               v.pack_version, v.manifest_sha256, v.retention_required
        FROM public.pk_packs AS p
        LEFT JOIN public.pk_pack_versions AS v ON v.pack_id = p.id
        ORDER BY p.pack_code COLLATE "C", v.pack_version COLLATE "C"
    """):
        pid = row["pack_id"]
        pack = packs_by_id.setdefault(pid, {
            "pack_code": row["pack_code"],
            "owner_code": row["owner_code"],
            "pack_kind": row["pack_kind"],
            "versions": [],
            "tenant_state": {"status": "ABSENT"},
        })
        if row["pack_version"] is not None:
            pack["versions"].append({
                "version": row["pack_version"],
                "manifest_sha256": row["manifest_sha256"],
                "retention_required": row["retention_required"],
            })

    for row in _rows(db, """
        SELECT i.pack_id, i.lifecycle_status, v.pack_version, i.row_version
        FROM public.pk_tenant_pack_installations AS i
        JOIN public.pk_pack_versions AS v
          ON v.id = i.pack_version_id AND v.pack_id = i.pack_id
        WHERE i.tenant_id = :tenant_id
    """, tenant_id):
        pack = packs_by_id.get(row["pack_id"])
        if pack is None:
            raise ValueError("PACK_REGISTRY_INCONSISTENT")
        status = row["lifecycle_status"]
        if status not in ("staged", "installed", "active", "disabled", "removed"):
            raise ValueError("PACK_STATE_UNKNOWN")
        pack["tenant_state"] = {
            "status": status.upper(),
            "version": row["pack_version"],
            "row_version": row["row_version"],
        }

    templates_by_id: dict[int, dict] = {}
    versions_by_id: dict[int, dict] = {}
    for row in _rows(db, """
        SELECT t.id AS template_id, t.template_code, t.owner_code,
               v.id AS template_version_id, v.template_version, v.template_sha256,
               v.industry_semantic_ref, v.operating_model_semantic_ref
        FROM public.pk_templates AS t
        LEFT JOIN public.pk_template_versions AS v ON v.template_id = t.id
        ORDER BY t.template_code COLLATE "C", v.template_version COLLATE "C"
    """):
        tid = row["template_id"]
        template = templates_by_id.setdefault(tid, {
            "template_code": row["template_code"],
            "owner_code": row["owner_code"],
            "versions": [],
            "tenant_state": {"status": "ABSENT"},
        })
        vid = row["template_version_id"]
        if vid is not None:
            version = {
                "version": row["template_version"],
                "template_sha256": row["template_sha256"],
                "industry_semantic_ref": row["industry_semantic_ref"],
                "operating_model_semantic_ref": row["operating_model_semantic_ref"],
                "requirements": [],
            }
            template["versions"].append(version)
            versions_by_id[vid] = version

    for row in _rows(db, """
        SELECT r.template_version_id, r.pack_code, r.pack_version, r.requirement_kind
        FROM public.pk_template_pack_requirements AS r
        ORDER BY r.template_version_id, r.pack_code COLLATE "C",
                 r.requirement_kind COLLATE "C", r.pack_version COLLATE "C"
    """):
        version = versions_by_id.get(row["template_version_id"])
        if version is None:
            raise ValueError("TEMPLATE_REQUIREMENT_INCONSISTENT")
        kind = row["requirement_kind"]
        if kind not in ("required", "optional", "incompatible"):
            raise ValueError("TEMPLATE_REQUIREMENT_UNKNOWN")
        version["requirements"].append({
            "pack_code": row["pack_code"], "version": row["pack_version"],
            "kind": kind.upper(),
        })

    for row in _rows(db, """
        SELECT b.template_id, v.template_version, b.row_version,
               b.selected_optional_packs
        FROM public.pk_tenant_template_bindings AS b
        JOIN public.pk_template_versions AS v
          ON v.id = b.template_version_id AND v.template_id = b.template_id
        WHERE b.tenant_id = :tenant_id
    """, tenant_id):
        template = templates_by_id.get(row["template_id"])
        if template is None:
            raise ValueError("TEMPLATE_REGISTRY_INCONSISTENT")
        selected = row["selected_optional_packs"]
        if not isinstance(selected, list):
            raise ValueError("TEMPLATE_SELECTION_INVALID")
        template["tenant_state"] = {
            "status": "APPLIED",
            "version": row["template_version"],
            "row_version": row["row_version"],
            "selected_optional_packs": sorted(selected, key=_key),
        }

    packs = sorted(packs_by_id.values(), key=lambda p: _key(p["pack_code"]))
    templates = sorted(templates_by_id.values(), key=lambda t: _key(t["template_code"]))
    for pack in packs:
        pack["versions"].sort(key=lambda v: _key(v["version"]))
    for template in templates:
        template["versions"].sort(key=lambda v: _key(v["version"]))
        for version in template["versions"]:
            version["requirements"].sort(
                key=lambda r: (_key(r["pack_code"]), _key(r["kind"]), _key(r["version"]))
            )
    return {
        "schema": "xbos.platform.pack-template-discovery.v1",
        "tenant_ref": tenant_id,
        "packs": packs,
        "templates": templates,
    }
