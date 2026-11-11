"""Source-only D1 SQL readers. No production dependency injection yet.

The session supplied here MUST be a least-privilege trusted connection to the
admitted neutral database; this module never connects or mutates on its own.
"""
from __future__ import annotations

from uuid import UUID
from sqlalchemy import text

from core.platform.security_authority import Lifecycle
from core.platform.security_authority.sql_repository import SQLSecurityRepository
from platform_admin.neutral_d1_pc5_binding_verifier import PersistedPC5BrowserLink

# Existing PC5 compatibility mapping is an independent identity authority:
# source_authority='xbos_browser_user', source_record_id=<decimal user_id>.
# A link without that canonical mapping must not become an authenticated read.
LINK_READ_SQL = text("""
    SELECT link.browser_session_id, link.user_id, link.tenant_id,
           link.branch_id, link.pc5_session_id, link.pc5_identity_id,
           link.expires_at, link.revoked_at
    FROM public.d1_pc5_browser_links AS link
    JOIN public.identity_compatibility_mappings AS m
      ON m.source_authority = 'xbos_browser_user'
     AND m.source_record_id = link.user_id::text
     AND m.identity_id = link.pc5_identity_id
    JOIN public.xbos_browser_sessions AS b
      ON b.session_id = link.browser_session_id
     AND b.user_id = link.user_id
     AND b.tenant_id = link.tenant_id
     AND b.branch_id = link.branch_id
    WHERE link.browser_session_id = :sid
      AND link.revoked_at IS NULL
      AND b.revoked_at IS NULL
""")
IDENTITY_STATUS_SQL = text("""
    SELECT status FROM public.identities WHERE id = :identity_id
""")


class D1SQLAuthorityReaders:
    def __init__(self, db):
        self.db = db

    def read_server_owned_link(self, browser_sid: UUID):
        if not isinstance(browser_sid, UUID):
            raise TypeError("EXPECTED_SERVER_VERIFIED_BROWSER_UUID")
        row = self.db.execute(LINK_READ_SQL, {"sid": str(browser_sid)}).mappings().one_or_none()
        if row is None:
            return None
        return PersistedPC5BrowserLink(
            browser_session_id=UUID(str(row["browser_session_id"])),
            user_id=int(row["user_id"]),
            tenant_id=int(row["tenant_id"]),
            branch_id=int(row["branch_id"]),
            pc5_session_id=UUID(str(row["pc5_session_id"])),
            pc5_identity_id=int(row["pc5_identity_id"]),
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    def read_pc5_session(self, pc5_session_id: UUID):
        if not isinstance(pc5_session_id, UUID):
            raise TypeError("EXPECTED_PC5_SESSION_UUID")
        return SQLSecurityRepository(self.db).session(pc5_session_id)

    def read_pc5_identity_status(self, identity_id: int):
        if not isinstance(identity_id, int) or identity_id <= 0:
            raise TypeError("EXPECTED_PC5_IDENTITY_ID")
        raw = self.db.execute(IDENTITY_STATUS_SQL, {"identity_id": identity_id}).scalar_one_or_none()
        return Lifecycle(raw) if raw is not None else None
