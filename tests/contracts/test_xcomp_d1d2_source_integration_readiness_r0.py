"""PCR V21 cross-lane D1-D2 source-contract and fail-closed adapter tests."""
from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_admin.neutral_d1_read_router import (
    readiness_router, get_verified_pc5_binding, BoundPC5Principal,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/platform/v1/xcomp_d1d2_readiness_source_contract_v1.json"


def client():
    app = FastAPI()
    app.include_router(readiness_router)
    return TestClient(app), app


def test_source_contract_exact_required_and_nonoperative():
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert c["schema"] == "xcomp.d1d2.readiness.source_contract.v1"
    assert c["candidate_endpoint"] == "/platform/xcomp/d1d2/readiness"
    assert c["method"] == "GET"
    assert c["response_schema"] == "xcomp.fe.readiness.v1"
    assert c["response_issuer"] == "PC5_PA_PK_SERVER_READ_ONLY"
    assert c["trust_producers"] == ["PC1", "PC4", "PC5", "PA", "PK"]
    assert set(c["response_required"]) >= {"tenant_id", "branch_id", "principal_id", "pc5", "pa", "pk", "pc4", "plan", "packs", "xafchat"}
    assert not c["mutation_authorized"] and not c["effective_merchant_authority"] and not c["hosted_admitted"]


def test_unauthenticated_readiness_denied():
    c,_ = client()
    r=c.get("/platform/xcomp/d1d2/readiness")
    assert r.status_code == 401
    assert r.json()["detail"] == "NEUTRAL_BEARER_REQUIRED"


def test_bearer_without_producer_is_default_denied():
    c,_=client()
    r=c.get("/platform/xcomp/d1d2/readiness", headers={"Authorization":"Bearer untrusted-token"})
    assert r.status_code == 503
    assert r.json()["detail"] == "SERVER_BROWSER_TO_PC5_SESSION_BINDING_ABSENT"


def test_even_injected_binding_cannot_promote_source_to_live_readiness():
    c,app=client()
    app.dependency_overrides[get_verified_pc5_binding] = lambda: BoundPC5Principal(
        session_id=UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        tenant_id=910001, branch_id=5,
    )
    r=c.get("/platform/xcomp/d1d2/readiness", headers={"Authorization":"Bearer nonoperative"})
    assert r.status_code == 503
    assert r.json()["detail"] == "D1D2_TRUSTED_READINESS_COMPOSER_NOT_ADMITTED"


def test_candidate_endpoint_remains_read_only():
    c,_=client()
    r=c.post("/platform/xcomp/d1d2/readiness",json={"activate":True})
    assert r.status_code == 405
