"""Candidate repository is hard-fenced against production WND/xbos DSNs."""
import pytest
from restaurant.g4a_canonical_product_pg_repository import PgProductCandidateStore


class ConnectionStub:
    def __init__(self, db, host, port, autocommit=False):
        self.params=dict(dbname=db,host=host,port=str(port))
        self.autocommit=autocommit
        self.closed=False
    def get_dsn_parameters(self):return self.params
    def close(self):self.closed=True


@pytest.mark.parametrize("db,host,port,auto,expected",[
 ("xbos","127.0.0.1",55449,False,"G4A_CANDIDATE_WRITES_NOT_PERMITTED_OUTSIDE_TEST_DB"),
 ("g4a_v24_native_product_test","10.0.0.5",55449,False,"G4A_CANDIDATE_WRITES_NOT_PERMITTED_OUTSIDE_TEST_DB"),
 ("g4a_v24_native_product_test","127.0.0.1",5432,False,"G4A_CANDIDATE_WRITES_NOT_PERMITTED_OUTSIDE_TEST_DB"),
 ("g4a_v24_native_product_test","127.0.0.1",55449,True,"G4A_AUTOCOMMIT_DENIED"),
])
def test_no_other_database_or_autocommit_can_write(db,host,port,auto,expected):
    connection=ConnectionStub(db,host,port,auto)
    store=PgProductCandidateStore(lambda: connection)
    with pytest.raises(RuntimeError,match=expected):
        with store.transaction():pass
    assert connection.closed


def test_invalid_connection_factory_is_denied():
    with pytest.raises(TypeError,match="G4A_PG_CONNECTION_FACTORY_REQUIRED"):
        PgProductCandidateStore(True)
