"""Deterministic SQLAlchemy metadata for existing and canonical XBOS models."""

from sqlalchemy import MetaData


# Existing explicitly named constraints retain their names. These templates provide
# deterministic fallbacks for previously unnamed objects. New canonical models must
# still give every business constraint and access-path index an explicit semantic name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
