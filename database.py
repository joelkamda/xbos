import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.persistence.database_config import resolve_database_url
from core.persistence.metadata import metadata


# Environment and the project environment file are the only application sources.
# Alembic may additionally supply its configured URL to the same resolver.
DATABASE_URL = resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.environ.get("XBOS_DB_POOL_SIZE", "5")),
    max_overflow=int(os.environ.get("XBOS_DB_MAX_OVERFLOW", "10")),
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base(metadata=metadata)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
