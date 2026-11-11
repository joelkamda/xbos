"""Test trusted D1 PC5 binding decisions using disposable server-side records."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core.platform.security_authority import ActorType, Lifecycle, SessionContext
from platform_admin.neutral_d1_pc5_binding_verifier import (
    PC5BindingDenied, PersistedPC5BrowserLink, VerifiedBrowserSession,
    verify_browser_to_pc5_binding,
)

NOW = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)
BSID = uuid4()
PSID = uuid4()


def state():
    browser = VerifiedBrowserSession(BSID, 42, 7, 11, NOW + timedelta(minutes=20))
    link = PersistedPC5BrowserLink(BSID, 42, 7, 11, PSID, 1002, NOW + timedelta(minutes=10))
    pc5 = SessionContext(8, PSID, 1002, 7, ActorType.HUMAN, 2,
                         NOW - timedelta(minutes=10), NOW + timedelta(minutes=8))
    data = {"browser": browser, "link": link, "pc5": pc5,
            "identity": Lifecycle.ACTIVE, "token": "server-validated-access"}
    return data


def bind(data):
    def access(token):
        if token != data["token"]:
            raise PC5BindingDenied("INVALID_BROWSER_TOKEN")
        return data["browser"]
    return verify_browser_to_pc5_binding(
        "server-validated-access", verify_browser_access=access,
        read_server_owned_link=lambda sid: data["link"] if sid == BSID else None,
        read_pc5_session=lambda sid: data["pc5"] if sid == PSID else None,
        read_pc5_identity_status=lambda uid: data["identity"] if uid == 1002 else None,
        clock=lambda: NOW,
    )


def test_live_server_owned_binding_positive_source_contract():
    principal = bind(state())
    assert principal.session_id == PSID and principal.tenant_id == 7 and principal.branch_id == 11


@pytest.mark.parametrize("field,transform", [
    ("browser", lambda x: replace(x, revoked_at=NOW)),
    ("browser", lambda x: replace(x, expires_at=NOW)),
    ("browser", lambda x: replace(x, tenant_id=8)),
    ("browser", lambda x: replace(x, user_id=43)),
    ("browser", lambda x: replace(x, branch_id=12)),
    ("link", lambda x: None),
    ("link", lambda x: replace(x, revoked_at=NOW)),
    ("link", lambda x: replace(x, expires_at=NOW)),
    ("link", lambda x: replace(x, pc5_identity_id=9999)),
    ("link", lambda x: replace(x, pc5_session_id=uuid4())),
    ("link", lambda x: replace(x, tenant_id=8)),
    ("link", lambda x: replace(x, branch_id=12)),
    ("pc5", lambda x: None),
    ("pc5", lambda x: replace(x, revoked_at=NOW)),
    ("pc5", lambda x: replace(x, expires_at=NOW)),
    ("pc5", lambda x: replace(x, tenant_id=8)),
    ("pc5", lambda x: replace(x, identity_id=9999)),
    ("pc5", lambda x: replace(x, actor_type=ActorType.SERVICE)),
    ("pc5", lambda x: replace(x, authenticated_at=NOW + timedelta(minutes=1))),
    ("identity", lambda x: Lifecycle.REVOKED),
    ("identity", lambda x: Lifecycle.SUSPENDED),
    ("identity", lambda x: None),
    ("token", lambda x: "forged-browser-token"),
])
def test_binding_fail_closed_on_revocation_forgery_context_and_identity(field, transform):
    data = state()
    data[field] = transform(data[field])
    with pytest.raises(PC5BindingDenied):
        bind(data)


def test_bearer_absent_denied():
    data = state()
    with pytest.raises(PC5BindingDenied, match="BEARER_REQUIRED"):
        verify_browser_to_pc5_binding(
            "", verify_browser_access=lambda t: data["browser"],
            read_server_owned_link=lambda sid: data["link"],
            read_pc5_session=lambda sid: data["pc5"],
            read_pc5_identity_status=lambda uid: data["identity"],
            clock=lambda: NOW,
        )


def test_unavailable_pc5_repository_denied():
    data = state()
    with pytest.raises(PC5BindingDenied, match="TRUSTED_AUTHORITY_UNAVAILABLE"):
        verify_browser_to_pc5_binding(
            "server-validated-access", verify_browser_access=lambda t: data["browser"],
            read_server_owned_link=lambda sid: data["link"],
            read_pc5_session=lambda sid: (_ for _ in ()).throw(RuntimeError("db down")),
            read_pc5_identity_status=lambda uid: data["identity"],
            clock=lambda: NOW,
        )


def test_untrusted_browser_reader_response_denied():
    data = state()
    with pytest.raises(PC5BindingDenied, match="BROWSER_VERIFIER_NOT_TRUSTED"):
        verify_browser_to_pc5_binding(
            data["token"], verify_browser_access=lambda t: {"tenant_id": 7},
            read_server_owned_link=lambda sid: data["link"],
            read_pc5_session=lambda sid: data["pc5"],
            read_pc5_identity_status=lambda uid: data["identity"],
            clock=lambda: NOW,
        )
