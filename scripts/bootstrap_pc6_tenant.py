#!/usr/bin/env python3
"""Bootstrap the bounded PC6 tenant profile through public Platform Core facades."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.neutral_proof import bootstrap_profile, deterministic_export, load_profile


LOCAL = {"localhost", "127.0.0.1", "::1"}


def _facades(session):
    from core.platform.operating_context import OperatingContextAuthority, SQLOperatingContextRepository
    from core.platform.party import PartyAuthority, SQLPartyRepository
    from core.platform.security_authority import SecurityAuthority, SQLSecurityRepository
    from core.platform.semantics import SemanticAuthority, SQLSemanticRepository
    from core.platform.structure import StructuralAuthority, SQLStructuralRepository
    return {
        "structure": StructuralAuthority(SQLStructuralRepository(session)),
        "party": PartyAuthority(SQLPartyRepository(session)),
        "semantics": SemanticAuthority(SQLSemanticRepository(session)),
        "operating_context": OperatingContextAuthority(SQLOperatingContextRepository(session)),
        "security": SecurityAuthority(SQLSecurityRepository(session)),
    }


def bootstrap(database_url: str, profile_path: Path, export_path: Path | None = None) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    url = make_url(database_url)
    if url.host not in LOCAL or url.get_backend_name() != "postgresql":
        raise RuntimeError("refusing non-local or non-PostgreSQL bootstrap target")
    profile = load_profile(profile_path)
    engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            with session.begin():
                authorities = _facades(session)
                result = bootstrap_profile(profile, authorities)
                if export_path:
                    state = {
                        "structure": json.loads(authorities["structure"].export(result["tenant_id"])),
                        "party": json.loads(authorities["party"].export(result["tenant_id"])),
                        "semantics": json.loads(authorities["semantics"].export(result["tenant_id"])),
                        "operating_context": authorities["operating_context"].export(result["tenant_id"]),
                        "identity": authorities["security"].export_identity(result["identity_id"]),
                    }
                    export_path.write_bytes(deterministic_export(profile, state))
    finally:
        engine.dispose()
    return {key: value for key, value in result.items() if key not in {"calendar", "identity_id"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "profiles/platform_core/pc6_second_tenant.json")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    try:
        result = bootstrap(args.database_url, args.profile, args.export)
    except Exception as exc:
        print(f"PC6_SECOND_TENANT_BOOTSTRAP=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("PC6_SECOND_TENANT_BOOTSTRAP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
