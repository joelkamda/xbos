from datetime import datetime, timedelta, timezone

import pytest
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected
from restaurant.customer_channel.swes_r48_protected_composition import (
    R48ProtectedAdmission,
    compose_r48_protected_app,
)


def candidate(**overrides):
    values = {
        "source_commit": "a" * 40,
        "tenant_id": 910001,
        "location_id": 5,
        "audience": "wnd-austin-track-a-ia0",
        "expires_utc": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    values.update(overrides)
    return R48ProtectedAdmission(**values)


@pytest.mark.parametrize("override", [
    {"tenant_id": 2},
    {"location_id": 6},
    {"audience": "wrong"},
    {"expires_utc": datetime.now(timezone.utc) - timedelta(seconds=1)},
    {"expires_utc": datetime.now(timezone.utc) + timedelta(hours=25)},
    {"source_commit": "not-a-commit"},
])
def test_wrong_release_scope_fails_before_verifier(override):
    with pytest.raises(CCEventRejected, match="SCOPE"):
        compose_r48_protected_app(
            admission=candidate(**override),
            authenticate_release_authority=lambda _: pytest.fail("must not call"),
        )


def test_unverified_release_cannot_mount():
    with pytest.raises(CCEventRejected, match="AUTHORITY"):
        compose_r48_protected_app(
            admission=candidate(), authenticate_release_authority=lambda _: False
        )


def test_missing_release_verifier_denied():
    with pytest.raises(CCEventRejected, match="AUTHORITY"):
        compose_r48_protected_app(
            admission=candidate(), authenticate_release_authority=None
        )
