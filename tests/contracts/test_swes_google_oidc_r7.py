"""TEST-only cryptographic fixtures; not an actual Google issuer or CEO proof."""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from jose import jwt

from platform_admin.swes_google_oidc_r7 import (
    ISSUER,
    JWKS_URL,
    TOKEN_URL,
    Challenge,
    OIDCConfig,
    OIDCHold,
    begin,
    digest,
    finish,
    owner_binding_gate,
    subject_digest,
)

CLIENT = "123456789-swes.apps.googleusercontent.com"
REDIRECT = "https://wnd-xafpay-demo-austin-backend.onrender.com/internal/swes/pa/oidc/callback"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
STATE = "s" * 48
NONCE = "n" * 48
VERIFIER = "v" * 60


@pytest.fixture
def config():
    return OIDCConfig(CLIENT, "private-test-only-client-secret", REDIRECT)


@pytest.fixture
def signer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    def b64(n):
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length()+7)//8, "big")).rstrip(b"=").decode()
    jwks = {"keys": [{"kid":"unit-test-key", "kty":"RSA",
                      "n":b64(public.n), "e":b64(public.e), "alg":"RS256", "use":"sig"}]}
    pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return pem, jwks


def valid_claims(**changes):
    claim = {
        "iss": ISSUER, "aud": CLIENT, "sub": "google-sub-unique-123",
        "nonce": NONCE, "iat": int(NOW.timestamp()),
        "exp": int((NOW+timedelta(minutes=10)).timestamp()),
    }
    claim.update(changes)
    return claim


def signed(signer, claims=None):
    return jwt.encode(claims or valid_claims(), signer[0], algorithm="RS256",
                      headers={"kid":"unit-test-key"})


class Store:
    def __init__(self, now=NOW):
        self.records = {}
        self.ch = Challenge(digest(STATE), digest(NONCE), VERIFIER, now,
                            now+timedelta(minutes=5))
    def issue(self, c):
        assert c.state_digest not in self.records
        self.records[c.state_digest] = c
    def consume(self, key):
        return self.records.pop(key, None)


class Response:
    def __init__(self, data):
        self._data=data
    def raise_for_status(self):
        pass
    def json(self):
        return self._data


class HTTP:
    def __init__(self, token, jwks):
        self.token,self.jwks=token,jwks;self.calls=[]
    def post(self, url, *, data, timeout, follow_redirects):
        assert url == TOKEN_URL and follow_redirects is False
        assert data["code_verifier"] == VERIFIER
        assert data["client_id"] == CLIENT
        assert data["redirect_uri"] == REDIRECT
        self.calls.append("exchange")
        return Response({"id_token":self.token})
    def get(self, url, *, timeout, follow_redirects):
        assert url == JWKS_URL and follow_redirects is False
        self.calls.append("jwks")
        return Response(self.jwks)


def make():
    s=Store();s.issue(s.ch);return s


def redeem(config, store, http):
    return finish(config,store,state=STATE,browser_state=STATE,
                  code="one_time_google_test_code_1234567",now=NOW,http=http)


def test_begin_issues_pkce_s256_state_nonce_and_durable_ticket(monkeypatch, config):
    seq=iter([STATE,NONCE,VERIFIER])
    monkeypatch.setattr("platform_admin.swes_google_oidc_r7.secrets.token_urlsafe",
                        lambda n:next(seq))
    store=Store()
    url,state=begin(config,store,now=NOW)
    params=parse_qs(urlsplit(url).query)
    assert state==STATE
    assert params["state"]==[STATE] and params["nonce"]==[NONCE]
    assert params["code_challenge_method"]==["S256"]
    assert params["redirect_uri"]==[REDIRECT]
    assert params["scope"]==["openid email"]
    assert params["code_challenge"][0]!=VERIFIER
    assert store.consume(digest(STATE)).code_verifier==VERIFIER
    assert store.consume(digest(STATE)) is None


def test_valid_google_signed_id_assertion_is_login_only(config, signer):
    stored=make()
    user=redeem(config,stored,HTTP(signed(signer),signer[1]))
    assert user.issuer==ISSUER and user.subject_sha256==subject_digest("google-sub-unique-123")
    assert user.tenant_id==910001 and user.assurance_level==1
    assert len(user.assertion_digest)==64
    with pytest.raises(OIDCHold,match="HOLD_INDEPENDENT_CEO_OWNER_BINDING_ABSENT"):
        owner_binding_gate(user,config,ceo_approval_registered=True)
    assert stored.consume(digest(STATE)) is None


@pytest.mark.parametrize("changed,hold", [
    ({"iss":"https://not-google.invalid"},"HOLD_ISSUER_MISMATCH"),
    ({"aud":"other-client.apps.googleusercontent.com"},"HOLD_INVALID_GOOGLE_SIGNATURE_OR_CLAIMS"),
    ({"azp":"another-client.apps.googleusercontent.com"},"HOLD_AUTHORIZED_PARTY_MISMATCH"),
    ({"nonce":"attacker-nonce"},"HOLD_NONCE_MISMATCH"),
    ({"sub":""},"HOLD_SUBJECT_INVALID"),
    ({"iat":int((NOW+timedelta(minutes=5)).timestamp())},"HOLD_TOKEN_CLOCK"),
    ({"iat":int((NOW-timedelta(hours=1)).timestamp())},"HOLD_TOKEN_CLOCK"),
    ({"exp":int((NOW+timedelta(hours=5)).timestamp())},"HOLD_TOKEN_CLOCK"),
])
def test_signed_wrong_claims_denied(changed,hold,config,signer):
    token=signed(signer,valid_claims(**changed))
    with pytest.raises(OIDCHold,match=hold):
        redeem(config,make(),HTTP(token,signer[1]))


def test_bad_signature_denied_even_with_matching_kid(config, signer):
    other = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    token = jwt.encode(valid_claims(),
                       other.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()),
                       algorithm="RS256",headers={"kid":"unit-test-key"})
    with pytest.raises(OIDCHold,match="HOLD_INVALID_GOOGLE_SIGNATURE_OR_CLAIMS"):
        redeem(config,make(),HTTP(token,signer[1]))


def test_untrusted_kid_denied(config,signer):
    keys={"keys":[{**signer[1]["keys"][0],"kid":"different"}]}
    with pytest.raises(OIDCHold,match="HOLD_UNTRUSTED_KEY_ID"):
        redeem(config,make(),HTTP(signed(signer),keys))


def test_hs256_algorithm_denied(config,signer):
    token=jwt.encode(valid_claims(),"dangerous-test-secret",algorithm="HS256",
                     headers={"kid":"unit-test-key"})
    with pytest.raises(OIDCHold,match="HOLD_UNTRUSTED_JWT_ALGORITHM"):
        redeem(config,make(),HTTP(token,signer[1]))


def test_replay_denied_before_second_external_exchange(config,signer):
    store=make();http=HTTP(signed(signer),signer[1])
    redeem(config,store,http)
    with pytest.raises(OIDCHold,match="HOLD_STATE_EXPIRED_USED_OR_WRONG_TENANT"):
        redeem(config,store,http)
    assert http.calls==["exchange","jwks"]


def test_wrong_browser_cookie_denied_before_consumption(config,signer):
    store=make();http=HTTP(signed(signer),signer[1])
    with pytest.raises(OIDCHold,match="HOLD_BROWSER_STATE_MISMATCH"):
        finish(config,store,state=STATE,browser_state="attacker",
               code="one_time_google_test_code_1234567",now=NOW,http=http)
    assert http.calls==[]
    assert store.consume(digest(STATE)) is not None


def test_expired_challenge_denied_before_external_call(config,signer):
    store=Store(now=NOW-timedelta(minutes=10));store.issue(store.ch)
    http=HTTP(signed(signer),signer[1])
    with pytest.raises(OIDCHold,match="HOLD_STATE_EXPIRED_USED_OR_WRONG_TENANT"):
        redeem(config,store,http)
    assert http.calls==[]


def test_verified_subject_requires_independently_registered_ceo_approval(config,signer):
    identity=redeem(config,make(),HTTP(signed(signer),signer[1]))
    approved=replace(config,owner_subject_sha256=identity.subject_sha256)
    with pytest.raises(OIDCHold,match="HOLD_INDEPENDENT_CEO_OWNER_BINDING_ABSENT"):
        owner_binding_gate(identity,approved,ceo_approval_registered=False)
    owner_binding_gate(identity,approved,ceo_approval_registered=True)
    wrong=replace(approved,owner_subject_sha256="a"*64)
    with pytest.raises(OIDCHold,match="HOLD_INDEPENDENT_CEO_OWNER_BINDING_ABSENT"):
        owner_binding_gate(identity,wrong,ceo_approval_registered=True)


def test_email_not_used_as_unique_subject(config,signer):
    claims=valid_claims(email="someone@example.org",email_verified=True)
    a=redeem(config,make(),HTTP(signed(signer,claims),signer[1]))
    b=redeem(config,make(),HTTP(signed(signer,{**claims,"email":"new@example.org"}),signer[1]))
    assert a.subject_sha256==b.subject_sha256


def test_wrong_callback_and_client_are_rejected_before_work():
    with pytest.raises(OIDCHold,match="HOLD_WRONG_CALLBACK"):
        OIDCConfig(CLIENT,"private-test-only-client-secret","https://production.example.com/oauth")
    with pytest.raises(OIDCHold,match="HOLD_OIDC_CLIENT_UNREGISTERED"):
        OIDCConfig("invalid-client","private-test-only-client-secret",REDIRECT)


def test_no_mfa_assertion_even_if_unsupported_amr_present(config,signer):
    user=redeem(config,make(),HTTP(signed(signer,valid_claims(amr=["mfa"])),signer[1]))
    assert user.assurance_level==1


def test_router_is_default_off_and_not_registered_in_startup(monkeypatch):
    from pathlib import Path

    from platform_admin.swes_google_oidc_router_r7 import _config, router
    monkeypatch.delenv("SWES_OIDC_ENABLED",raising=False)
    with pytest.raises(OIDCHold,match="HOLD_OIDC_NOT_ADMITTED"):
        _config()
    startup=(Path(__file__).resolve().parents[2]/"startup.py").read_text(encoding="utf-8")
    assert "swes_google_oidc_router_r7" not in startup
    assert "swes_google_oidc" not in startup
    assert any(route.path.endswith("/callback") for route in router.routes)


def test_sql_store_rejects_missing_or_invalid_encryption_key():
    from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore
    with pytest.raises(OIDCHold,match="HOLD_CHALLENGE_SEAL_KEY_INVALID"):
        SQLChallengeStore(object(),fernet_key="not-a-real-fernet-key")
    with pytest.raises(OIDCHold,match="HOLD_CHALLENGE_SEAL_KEY_ABSENT"):
        SQLChallengeStore(object(),fernet_key=None)


def test_sql_challenge_store_emits_atomic_delete_and_seals_pkce(monkeypatch):
    from cryptography.fernet import Fernet

    import platform_admin.swes_google_oidc_sql_r7 as store_module
    key=Fernet.generate_key().decode()
    calls=[]
    records={}
    class Result:
        def __init__(self,row=None):self.row=row
        def scalar_one(self):return "wnd_xafpay_demo_austin_db"
        def mappings(self):return self
        def first(self):return self.row
    class Session:
        def execute(self,statement,params=None):
            sql=str(statement);params=params or {}
            calls.append(sql)
            if sql=="SELECT current_database()":return Result()
            if sql.lstrip().startswith("INSERT INTO public.swes_pa_oidc_challenges"):
                assert b"v"*60 not in params["verifier"]
                records[params["state"]]={
                    "state_digest":params["state"],"nonce_digest":params["nonce"],
                    "verifier_ciphertext":params["verifier"],"tenant_id":params["tenant"],
                    "created_at":params["created"],"expires_at":params["expires"],
                }
                return Result()
            if sql.lstrip().startswith("DELETE FROM public.swes_pa_oidc_challenges"):
                assert "RETURNING" in sql and "tenant_id=:tenant" in sql
                return Result(records.pop(params["state"],None))
            raise AssertionError(sql)
    class Factory:
        def begin(self):
            class Bound:
                def __enter__(self):return Session()
                def __exit__(self,*args):pass
            return Bound()
    monkeypatch.setattr(store_module,"sessionmaker",lambda **kwargs:Factory())
    store=store_module.SQLChallengeStore(object(),fernet_key=key)
    challenge=Challenge(digest(STATE),digest(NONCE),VERIFIER,NOW,NOW+timedelta(minutes=5))
    store.issue(challenge)
    assert store.consume(digest(STATE))==challenge
    assert store.consume(digest(STATE)) is None
    assert len([x for x in calls if x.lstrip().startswith("DELETE FROM")])==2


def test_sql_challenge_wrong_database_denies_before_insert(monkeypatch):
    from cryptography.fernet import Fernet

    import platform_admin.swes_google_oidc_sql_r7 as store_module
    class Session:
        def execute(self,statement,params=None):
            assert str(statement)=="SELECT current_database()"
            class Result:
                def scalar_one(self):return "a_different_db"
            return Result()
    class Factory:
        def begin(self):
            class Bound:
                def __enter__(self):return Session()
                def __exit__(self,*args):pass
            return Bound()
    monkeypatch.setattr(store_module,"sessionmaker",lambda **kwargs:Factory())
    store=store_module.SQLChallengeStore(object(),fernet_key=Fernet.generate_key().decode())
    with pytest.raises(OIDCHold,match="HOLD_WRONG_DATABASE"):
        store.issue(Challenge(digest(STATE),digest(NONCE),VERIFIER,NOW,NOW+timedelta(minutes=5)))


def test_pc5_initial_enrollment_rejects_unapproved_subject_before_any_database(config):
    from platform_admin.swes_google_oidc_r7 import VerifiedIdentity
    from platform_admin.swes_google_pc5_enrollment_r7 import enroll_verified_ceo
    class NoDB:
        def execute(self,*args,**kwargs):
            raise AssertionError("NO_DB_WITHOUT_VERIFIED_OWNER")
    identity=VerifiedIdentity(ISSUER,subject_digest("operator-claim"),CLIENT,NOW,
                              "d"*64,910001,1)
    with pytest.raises(OIDCHold,match="HOLD_INDEPENDENT_CEO_OWNER_BINDING_ABSENT"):
        enroll_verified_ceo(db_session=NoDB(),identity=identity,config=config,
                            ceo_approval_registered=True,at=NOW)


def test_pc5_initial_enrollment_denies_wrong_database_even_with_owner_pin(config):
    from platform_admin.swes_google_oidc_r7 import VerifiedIdentity
    from platform_admin.swes_google_pc5_enrollment_r7 import enroll_verified_ceo
    identity=VerifiedIdentity(ISSUER,subject_digest("test-owner"),CLIENT,NOW,
                              "d"*64,910001,1)
    approved=replace(config,owner_subject_sha256=identity.subject_sha256)
    class WrongDB:
        def execute(self,*args,**kwargs):
            class R:
                def scalar_one(self):return "production"
            return R()
    with pytest.raises(OIDCHold,match="HOLD_WRONG_DATABASE"):
        enroll_verified_ceo(db_session=WrongDB(),identity=identity,config=approved,
                            ceo_approval_registered=True,at=NOW)


def test_pc5_initial_enrollment_never_claims_admin_allowed(monkeypatch,config):
    from types import SimpleNamespace

    import platform_admin.swes_google_pc5_enrollment_r7 as enroll_module
    from core.platform.security_authority import Decision
    from platform_admin.swes_google_oidc_r7 import VerifiedIdentity

    identity=VerifiedIdentity(ISSUER,subject_digest("cryptographic-test-owner"),CLIENT,NOW,
                              "d"*64,910001,1)
    approved=replace(config,owner_subject_sha256=identity.subject_sha256)
    events=[]
    class Result:
        def __init__(self,value):self.value=value
        def scalar_one(self):return self.value
        def scalar_one_or_none(self):return self.value
        def one(self):return self.value
    class Session:
        def execute(self,stmt,params=None):
            sql=str(stmt)
            if sql=="SELECT current_database()":return Result("wnd_xafpay_demo_austin_db")
            if "FROM public.tenants" in sql:
                assert "FOR UPDATE" in sql and params["t"]==910001
                return Result(910001)
            if "count(*) FROM public.identity_memberships" in sql:
                return Result((0,0,0))
            raise AssertionError(sql)
    class Repo:
        def permission(self,code):
            return None
    class Authority:
        def __init__(self,_repo):self.repository=Repo()
        def create_identity(self,**kwargs):
            events.append(("identity",kwargs))
            return SimpleNamespace(id=42,public_id="00000000-0000-4000-8000-000000000001")
        def add_membership(self,**kwargs):events.append(("membership",kwargs))
        def register_permission(self,**kwargs):events.append(("permission",kwargs))
        def create_role(self,**kwargs):events.append(("role",kwargs))
        def assign_role(self,**kwargs):events.append(("assignment",kwargs))
        def create_session(self,**kwargs):
            events.append(("session",kwargs))
            return SimpleNamespace(public_id="00000000-0000-4000-8000-000000000002")
        def authorize(self,req):
            events.append(("authorize",req))
            return SimpleNamespace(decision=Decision.REQUIRE_STEP_UP,required_assurance=2)
        def append_audit(self,envelope):events.append(("audit",envelope))
    monkeypatch.setattr(enroll_module,"SecurityAuthority",Authority)
    monkeypatch.setattr(enroll_module,"SQLSecurityRepository",lambda session:object())
    result=enroll_module.enroll_verified_ceo(
        db_session=Session(),identity=identity,config=approved,
        ceo_approval_registered=True,at=NOW)
    assert result.authorization_decision=="require_step_up"
    assert result.required_assurance==2 and result.operational_admission is False
    assert [event[0] for event in events]==[
        "identity","membership","permission","role","assignment",
        "session","authorize","audit"]
    assert events[3][1]["permissions"]==("pa.merchant.admin",)
    assert events[3][1]["tenant_id"]==910001
    assert events[5][1]["assurance_level"]==1
    assert events[6][1].tenant_id==910001
    assert events[7][1].outcome=="step_up_required"


def test_first_owner_replay_and_existing_admin_prestate_fail_closed(monkeypatch,config):
    import platform_admin.swes_google_pc5_enrollment_r7 as enrollment
    from platform_admin.swes_google_oidc_r7 import VerifiedIdentity
    identity=VerifiedIdentity(ISSUER,subject_digest("first-owner"),CLIENT,NOW,
                              "d"*64,910001,1)
    approved=replace(config,owner_subject_sha256=identity.subject_sha256)
    class Result:
        def __init__(self,v):self.v=v
        def scalar_one(self):return self.v
        def scalar_one_or_none(self):return self.v
        def one(self):return self.v
    class Session:
        def execute(self,stmt,params=None):
            q=str(stmt)
            if q=="SELECT current_database()":return Result("wnd_xafpay_demo_austin_db")
            if "FROM public.tenants" in q:return Result(910001)
            if "count(*) FROM public.identity_memberships" in q:return Result((1,1,1))
            raise AssertionError(q)
    with pytest.raises(OIDCHold,match="HOLD_FIRST_OPERATOR_ALREADY_ESTABLISHED"):
        enrollment.enroll_verified_ceo(
            db_session=Session(),identity=identity,config=approved,
            ceo_approval_registered=True,at=NOW)
