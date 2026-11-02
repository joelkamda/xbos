import hashlib

import pytest
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected
from restaurant.customer_channel.swes_r48_ia0_ingest_auth import authorize_cc_ingest


def test_missing_secret(monkeypatch):
    monkeypatch.delenv("XAFPAY_CC_WND_IA0_INGEST_TOKEN_SHA256", raising=False)
    with pytest.raises(CCEventRejected):
        authorize_cc_ingest(None, bearer="a"*64)

def test_invalid_token(monkeypatch):
    monkeypatch.setenv("XAFPAY_CC_WND_IA0_INGEST_TOKEN_SHA256",hashlib.sha256(b"a"*64).hexdigest())
    with pytest.raises(CCEventRejected):
        authorize_cc_ingest(None, bearer="b"*64)

def test_missing_role(monkeypatch):
    monkeypatch.setenv("XAFPAY_CC_WND_IA0_INGEST_TOKEN_SHA256",hashlib.sha256(b"a"*64).hexdigest())
    class DB:
        def execute(self,*args,**kwargs): return self
        def all(self): return []
    with pytest.raises(CCEventRejected):
        authorize_cc_ingest(DB(), bearer="a"*64)
