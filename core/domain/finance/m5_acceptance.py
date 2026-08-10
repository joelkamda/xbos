"""M5 semantic manifest and unchanged canonical-lineage authority."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from .m4_acceptance import EXPECTED_HEAD,EXPECTED_LINEAGE,live_migration_lineage

class M5AcceptanceError(RuntimeError):
    def __init__(self,code,detail):super().__init__(detail);self.code=code
def semantic_sha256(path):
    value=json.loads(Path(path).read_text(encoding="utf-8"));return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def validate_release_manifest(root):
    manifest=json.loads((root/"contracts/finance/v1/m5_release_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("baseline_code")!="XBOS_M5_COMPLETE_FINANCIAL_LIFECYCLES_RELEASE":raise M5AcceptanceError("unexpected_manifest","baseline code")
    if manifest.get("canonical_head")!=EXPECTED_HEAD:raise M5AcceptanceError("unexpected_head",repr(manifest.get("canonical_head")))
    components=manifest.get("components",[])
    if len(components)!=6:raise M5AcceptanceError("component_count",repr(components))
    for sequence,component in enumerate(components,1):
        if component.get("sequence")!=sequence:raise M5AcceptanceError("sequence",repr(component))
        actual=semantic_sha256(root/component["path"])
        if actual!=component["semantic_sha256"]:raise M5AcceptanceError("semantic_fingerprint_mismatch",f"{component['path']}: expected {component['semantic_sha256']}, found {actual}")
    if live_migration_lineage(root)!=EXPECTED_LINEAGE:raise M5AcceptanceError("lineage_changed","M5 must not change canonical lineage")
    if tuple((root/"alembic_neutral/versions").glob("m5*.py")):raise M5AcceptanceError("unexpected_m5_migration","M5 is schema neutral")
    return len(components)
