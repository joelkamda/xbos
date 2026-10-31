"""Reject unsafe hosted role provisioning before opening a database connection."""
from __future__ import annotations

import pytest

from scripts import swes_r13_oidc_role_admission as target


def test_reject_missing_distinct_secret(monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
    monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://wnd_xafpay_demo_austin_db_user:owner@db.internal/"
        "wnd_xafpay_demo_austin_db",
    )
    monkeypatch.delenv("SWES_OIDC_WRITER_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="HOLD_RESTRICTED_WRITER_CREDENTIAL_NOT_CONFIGURED"):
        target.controlled_urls(require_writer=True)


@pytest.mark.parametrize(
    ("writer", "expected"),
    [
        (
            "postgresql://wnd_xafpay_demo_austin_db_user:abcdefghijklmnopqrstuvwxyz1234567890@db.internal/wnd_xafpay_demo_austin_db",
            "HOLD_WRITER_CREDENTIAL_SCOPE_MISMATCH",
        ),
        (
            "postgresql://swes_oidc_austin_writer_r11:abcdefghijklmnopqrstuvwxyz1234567890@other.internal/wnd_xafpay_demo_austin_db",
            "HOLD_WRITER_CREDENTIAL_SCOPE_MISMATCH",
        ),
        (
            "postgresql://swes_oidc_austin_writer_r11:short@db.internal/wnd_xafpay_demo_austin_db",
            "HOLD_WRITER_CREDENTIAL_SCOPE_MISMATCH",
        ),
    ],
)
def test_reject_unsafe_writer_url(monkeypatch, writer, expected):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
    monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://wnd_xafpay_demo_austin_db_user:owner@db.internal/"
        "wnd_xafpay_demo_austin_db",
    )
    monkeypatch.setenv("SWES_OIDC_WRITER_DATABASE_URL", writer)
    with pytest.raises(RuntimeError, match=expected):
        target.controlled_urls(require_writer=True)


def test_accept_scoped_url_without_db_network_call(monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
    monkeypatch.setenv("XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED", "0")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://wnd_xafpay_demo_austin_db_user:owner@db.internal/"
        "wnd_xafpay_demo_austin_db",
    )
    monkeypatch.setenv(
        "SWES_OIDC_WRITER_DATABASE_URL",
        "postgresql+psycopg2://swes_oidc_austin_writer_r11:abcdefghijklmnopqrstuvwxyz1234567890@db.internal/wnd_xafpay_demo_austin_db",
    )
    owner, writer = target.controlled_urls(require_writer=True)
    assert owner.username == "wnd_xafpay_demo_austin_db_user"
    assert writer.username == "swes_oidc_austin_writer_r11"
