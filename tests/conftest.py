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