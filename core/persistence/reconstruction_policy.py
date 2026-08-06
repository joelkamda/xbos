"""Safety policy for the isolated M1.2 reconstruction candidate."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url


RECONSTRUCTION_DATABASE_NAME = "xbos_track_b_reconstruction_test"
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RECONSTRUCTION_REVISION = "m12_source_state_001"


class UnsafeReconstructionTarget(RuntimeError):
    """Raised when reconstruction is aimed outside its disposable boundary."""


def validate_reconstruction_url(value: str | URL) -> URL:
    """Return a parsed URL only when it names the exact local disposable DB."""

    url = value if isinstance(value, URL) else make_url(value)

    if url.get_backend_name() != "postgresql":
        raise UnsafeReconstructionTarget(
            "M1.2 reconstruction requires PostgreSQL"
        )

    if url.host not in LOCAL_DATABASE_HOSTS:
        raise UnsafeReconstructionTarget(
            f"Refusing non-local reconstruction host: {url.host!r}"
        )

    if url.database != RECONSTRUCTION_DATABASE_NAME:
        raise UnsafeReconstructionTarget(
            "Refusing database other than "
            f"{RECONSTRUCTION_DATABASE_NAME!r}: {url.database!r}"
        )

    return url
