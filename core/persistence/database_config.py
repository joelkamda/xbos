"""Dependency-free database URL resolution shared by the app and Alembic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


class DatabaseConfigurationError(RuntimeError):
    """Raised when XBOS cannot resolve a safe PostgreSQL database URL."""


def _read_env_value(path: Path, key: str) -> Optional[str]:
    if not path.is_file():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        if "=" not in line:
            continue

        candidate_key, candidate_value = line.split("=", 1)

        if candidate_key.strip() != key:
            continue

        value = candidate_value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        return value or None

    return None


def resolve_database_url(
    *,
    configured_url: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
    env_file: Optional[Path] = None,
) -> str:
    """
    Resolve one PostgreSQL URL for both application and migration processes.

    Precedence:
    1. DATABASE_URL from the supplied or process environment;
    2. DATABASE_URL from the project environment file;
    3. an explicitly supplied Alembic/configuration fallback.

    No credential-bearing URL is embedded in source code.
    """

    environment = os.environ if environ is None else environ
    selected_env_file = DEFAULT_ENV_FILE if env_file is None else Path(env_file)

    database_url = (
        environment.get("DATABASE_URL")
        or _read_env_value(selected_env_file, "DATABASE_URL")
        or configured_url
    )

    if not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required in the environment, the project environment "
            "file, or explicit migration configuration"
        )

    try:
        parsed = urlsplit(database_url)
    except ValueError as exc:
        raise DatabaseConfigurationError("DATABASE_URL is not a valid URL") from exc

    backend = parsed.scheme.split("+", 1)[0]

    if not parsed.scheme:
        raise DatabaseConfigurationError("DATABASE_URL is not a valid URL")

    if backend != "postgresql":
        raise DatabaseConfigurationError(
            "XBOS persistence requires PostgreSQL; refusing configured backend "
            f"{backend!r}"
        )

    if not parsed.path.lstrip("/"):
        raise DatabaseConfigurationError("DATABASE_URL must name a database")

    return database_url
