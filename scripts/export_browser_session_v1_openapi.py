"""Deterministic public OpenAPI export for xbos.browser-session.v1.

Run with test-only XBOS settings; imports FastAPI route declarations but makes
no database connections, schema changes, login calls or provider calls.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import app
OUTPUT = ROOT / "contracts" / "auth" / "v1" / "browser-session-v1.openapi.json"
MANIFEST = ROOT / "contracts" / "auth" / "v1" / "browser-session-v1.manifest.json"
VERSION = "xbos.browser-session.v1"
GENERATOR = "xbos-public-openapi-export-v1"
PATHS = (
    "/kernel/browser-session/v1/login",
    "/kernel/browser-session/v1/continue",
    "/kernel/browser-session/v1/logout",
    "/kernel/auth/me",
)

def canonical(data):
    return (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    original = app.openapi()
    if not all(p in original["paths"] for p in PATHS):
        raise ValueError("PUBLIC_ROUTE_MISSING")
    paths = {p: original["paths"][p] for p in PATHS}
    all_schemas = original["components"]["schemas"]
    names = set()
    next_refs = set(re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", json.dumps(paths)))
    while next_refs:
        name = next_refs.pop()
        if name in names:
            continue
        if name not in all_schemas:
            raise ValueError(f"PUBLIC_SCHEMA_MISSING:{name}")
        names.add(name)
        next_refs.update(re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", json.dumps(all_schemas[name])))
        next_refs.difference_update(names)
    exported = {
        "openapi": original["openapi"],
        "info": {"title": "XBOS Browser Session V1", "version": VERSION},
        "paths": paths,
        "components": {"schemas": {name: all_schemas[name] for name in sorted(names)}},
    }
    body = canonical(exported)
    manifest = canonical({
        "contract_id": VERSION,
        "backend_base_commit": "e0ae0123cec02cb2cb294e2bbad09df341be17c1",
        "source": "main:app.openapi()",
        "generator_version": GENERATOR,
        "public_paths": list(PATHS),
        "public_schema_count": len(names),
        "generated_file": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "generated_sha256": sha(body),
    })
    if args.check:
        result = OUTPUT.is_file() and OUTPUT.read_bytes() == body and MANIFEST.is_file() and MANIFEST.read_bytes() == manifest
        print("PUBLIC_CONTRACT_DRIFT=" + ("PASS" if result else "FAIL"))
        return 0 if result else 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(body)
    MANIFEST.write_bytes(manifest)
    print("PUBLIC_CONTRACT_EXPORT=PASS SCHEMAS=" + str(len(names)) + " SHA256=" + sha(body))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
