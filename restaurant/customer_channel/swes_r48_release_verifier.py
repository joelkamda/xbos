"""Independent PCR-signed R48 release validation; never an env-only grant."""
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .swes_r48_cc_event_validation import CCEventRejected
from .swes_r48_protected_composition import R48ProtectedAdmission

SERVICE = "srv-db3vej67bikc73ai2080"
HOST = "wnd-xafpay-demo-austin-backend.onrender.com"


@dataclass(frozen=True, slots=True)
class SignedR48Release:
    admission: R48ProtectedAdmission
    service_id: str
    hostname: str
    issued_at: datetime
    signature: bytes

    def canonical_bytes(self) -> bytes:
        a = self.admission
        data = {
            "audience": a.audience, "expires_utc": a.expires_utc.isoformat(),
            "hostname": self.hostname, "issued_at": self.issued_at.isoformat(),
            "location_id": a.location_id, "service_id": self.service_id,
            "source_commit": a.source_commit, "tenant_id": a.tenant_id,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def verify_signed_release(*, grant: SignedR48Release,
                          public_key: bytes, externally_pinned_digest: str,
                          environment: Mapping[str, str]) -> bool:
    """Require independently pinned signer, exact live commit and valid signature."""
    if (not isinstance(grant, SignedR48Release)
        or not isinstance(public_key, bytes) or len(public_key) != 32
        or not isinstance(externally_pinned_digest, str)
        or len(externally_pinned_digest) != 64
        or not hmac.compare_digest(
            hashlib.sha256(public_key).hexdigest(), externally_pinned_digest
        )):
        raise CCEventRejected("R48_INDEPENDENT_SIGNER_PIN_REQUIRED")
    now = datetime.now(timezone.utc)
    if (grant.issued_at.tzinfo is None
        or not grant.issued_at <= now < grant.admission.expires_utc
        or grant.service_id != SERVICE or grant.hostname != HOST
        or environment.get("RENDER") != "true"
        or environment.get("RENDER_SERVICE_ID") != SERVICE
        or environment.get("RENDER_EXTERNAL_HOSTNAME") != HOST
        or environment.get("RENDER_GIT_COMMIT", "").lower() != grant.admission.source_commit
        or not isinstance(grant.signature, bytes) or len(grant.signature) != 64):
        raise CCEventRejected("R48_RELEASE_CONTEXT_INVALID")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            grant.signature, grant.canonical_bytes()
        )
    except (InvalidSignature, ValueError) as exc:
        raise CCEventRejected("R48_RELEASE_SIGNATURE_INVALID") from exc
    return True
