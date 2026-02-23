from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# ---------------------------------------------------------
# DATABASE URL (PostgreSQL by default)
# ---------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:Becky%408282@localhost:5432/xbos"
)

# ---------------------------------------------------------
# ENGINE (Postgres pool settings)
# ---------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# ---------------------------------------------------------
# SESSION FACTORY
# ---------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# ---------------------------------------------------------
# BASE CLASS
# ---------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------
# FASTAPI DEPENDENCY → Inject DB session into route handlers
# ---------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
