"""R13 hosted migration runner: never make a database connection in gate negatives."""
from __future__ import annotations

import pytest

from scripts import swes_r13_oidc_hosted_admission as runner


@pytest.mark.parametrize(
    ("login", "checkout", "expected"),
    [
        ("true", "0", "HOLD_OIDC_LOGIN_NOT_EXPLICITLY_OFF"),
        ("false", "1", "HOLD_CHECKOUT_NOT_EXPLICITLY_OFF"),
        ("false", "", "HOLD_CHECKOUT_NOT_EXPLICITLY_OFF"),
        ("FALSE", "0", "HOLD_OIDC_LOGIN_NOT_EXPLICITLY_OFF"),
    ],
)
def test_disabled_flags_fail_closed(monkeypatch, login, checkout, expected):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("SWES_OIDC_ENABLED", login)
    monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", checkout)
    with pytest.raises(RuntimeError, match=expected):
        runner.require_scope()


def test_dedicated_app_url_is_explicit(monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
    monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="HOLD_WND_DATABASE_CREDENTIAL_ABSENT"):
        runner.require_scope()
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    assert runner.require_scope() == "postgresql://unused"
