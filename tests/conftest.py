import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


TEST_DATABASE_NAME = "xbos_track_b_test"
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _read_database_url() -> str:
    env_path = Path(".env")

    if not env_path.exists():
        raise RuntimeError("Local .env file is required for characterization tests")

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise RuntimeError("DATABASE_URL is missing from .env")


base_url = make_url(_read_database_url())

if base_url.host not in LOCAL_DATABASE_HOSTS:
    raise RuntimeError(
        f"Refusing non-local PostgreSQL host: {base_url.host!r}"
    )

test_url = base_url.set(database=TEST_DATABASE_NAME)

if test_url.database != TEST_DATABASE_NAME:
    raise RuntimeError("Characterization test database safety check failed")

os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def app():
    from app import app as fastapi_app
    from database import engine

    if engine.url.database != TEST_DATABASE_NAME:
        raise RuntimeError(
            f"Refusing test run against database: {engine.url.database!r}"
        )

    return fastapi_app


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client

TEST_USERNAME = "track_b_characterization_admin"
TEST_PASSWORD = "track-b-test-only-password"


@pytest.fixture(scope="session")
def wnd_test_identity(app):
    from core.auth.password_service import PasswordService
    from core.tenants.tenant_model import Branch, Tenant
    from core.users.user_model import User
    from database import SessionLocal

    db = SessionLocal()

    try:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.id == 2, Tenant.code == "CM001")
            .one()
        )
        branch = (
            db.query(Branch)
            .filter(
                Branch.id == 1,
                Branch.tenant_id == tenant.id,
                Branch.branch_code == "BR001",
            )
            .one()
        )

        user = (
            db.query(User)
            .filter(User.username == TEST_USERNAME)
            .one_or_none()
        )

        password_hash = PasswordService().hash(TEST_PASSWORD)

        if user is None:
            user = User(
                username=TEST_USERNAME,
                password_hash=password_hash,
                full_name="Track B Characterization Admin",
                role="admin",
                tenant_id=tenant.id,
                branch_id=branch.id,
                is_active=True,
            )
            db.add(user)
        else:
            user.password_hash = password_hash
            user.full_name = "Track B Characterization Admin"
            user.role = "admin"
            user.tenant_id = tenant.id
            user.branch_id = branch.id
            user.is_active = True

        db.commit()
        db.refresh(user)

        return {
            "user_id": user.id,
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
            "tenant_id": tenant.id,
            "tenant_code": tenant.code,
            "branch_id": branch.id,
            "branch_code": branch.branch_code,
        }
    finally:
        db.close()


@pytest.fixture()
def auth_headers(client, wnd_test_identity):
    response = client.post(
        "/kernel/auth/login",
        headers={
            "X-Tenant-Code": wnd_test_identity["tenant_code"],
            "X-Branch-Code": wnd_test_identity["branch_code"],
        },
        json={
            "username": wnd_test_identity["username"],
            "password": wnd_test_identity["password"],
        },
    )

    assert response.status_code == 200, response.text

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Code": wnd_test_identity["tenant_code"],
        "X-Branch-Code": wnd_test_identity["branch_code"],
    }
