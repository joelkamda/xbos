"""R48 protected WND composition: explicit release authority, never main:app.

Credentials alone are insufficient. An externally authenticated, exact-source
release decision must install this composition through a protected entrypoint.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from .swes_r48_cc_event_validation import TENANT, CCEventRejected
from .swes_r48_cc_https_attestor import attest_cc_signed_sender

RELEASE_AUDIENCE = "wnd-austin-track-a-ia0"
LOCATION = 5


@dataclass(frozen=True, slots=True)
class R48ProtectedAdmission:
    """Documentary release values alone confer no authorization."""
    source_commit: str
    tenant_id: int
    location_id: int
    audience: str
    expires_utc: datetime


def compose_r48_protected_app(*, admission: R48ProtectedAdmission,
                              authenticate_release_authority) -> FastAPI:
    """Construct a separate protected instance after external authority proof.

    authenticate_release_authority must validate protected, independently
    pinned release evidence outside the WND process. No environment switch,
    untrusted HTTP request, or proof-bearing JSON can call this through main.
    """
    if not isinstance(admission, R48ProtectedAdmission):
        raise CCEventRejected("R48_PROTECTED_ADMISSION_REQUIRED")
    now = datetime.now(timezone.utc)
    if (admission.tenant_id != TENANT
        or admission.location_id != LOCATION
        or admission.audience != RELEASE_AUDIENCE
        or admission.expires_utc.tzinfo is None
        or not now < admission.expires_utc <= now + timedelta(hours=24)
        or len(admission.source_commit) != 40
        or any(x not in "0123456789abcdef" for x in admission.source_commit)):
        raise CCEventRejected("R48_RELEASE_SCOPE_INVALID")
    if (not callable(authenticate_release_authority)
        or authenticate_release_authority(admission) is not True):
        raise CCEventRejected("R48_RELEASE_AUTHORITY_UNVERIFIED")
    from startup import create_app
    return create_app(r48_receipt_attestor=attest_cc_signed_sender)


def compose_r48_signed_release_app(*, grant, signer_public_key: bytes,
                                   independently_pinned_digest: str,
                                   hosted_environment) -> FastAPI:
    """Trusted server-owned composition, never an HTTP or default entrypoint.

    The caller must supply independently pinned signer custody and PCR's
    signed exact-source release grant. Env settings cannot self-authorize.
    """
    from .swes_r48_release_verifier import verify_signed_release

    verified = verify_signed_release(
        grant=grant, public_key=signer_public_key,
        externally_pinned_digest=independently_pinned_digest,
        environment=hosted_environment,
    )
    if verified is not True:
        raise CCEventRejected("R48_RELEASE_NOT_VERIFIED")
    return compose_r48_protected_app(
        admission=grant.admission,
        authenticate_release_authority=lambda candidate: (
            candidate == grant.admission and verified is True
        ),
    )
