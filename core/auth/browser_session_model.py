"""Registry storage, not permission authority. Never store raw credentials."""
from sqlalchemy import Column, DateTime, Integer, String
from database import Base

class BrowserSession(Base):
    __tablename__ = "xbos_browser_sessions"
    session_id = Column(String(36), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    tenant_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revocation_reason = Column(String(64), nullable=True)
    current_refresh_jti = Column(String(64), nullable=False)
    previous_refresh_jti = Column(String(64), nullable=True)
    previous_refresh_valid_until = Column(DateTime(timezone=True), nullable=True)
    last_rotated_at = Column(DateTime(timezone=True), nullable=False)
