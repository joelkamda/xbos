"""TEST-only process-level network guard. Not an OS firewall or production sandbox.

Only Python socket calls to 127.0.0.1:55439 are permitted. The genuine
psycopg/libpq connection is separately pinned to the same host/port by seed.py.
No real WND data may be processed until an independent security assessment
accepts these controls and any residual native-library/subprocess risk.
"""
import ipaddress
import socket
import threading
from functools import wraps

_pair_internal=threading.local()

_installed=False

def allow(addr):
    if not isinstance(addr,tuple) or len(addr)<2:
        raise PermissionError("G3_TEST_OUTBOUND_ENDPOINT_NOT_RECOGNIZED")
    host,port=addr[0],addr[1]
    if host not in ("localhost","127.0.0.1","::1"):
        raise PermissionError("G3_TEST_EXTERNAL_HOST_DENIED")
    if int(port)!=55439:
        raise PermissionError("G3_TEST_OUTBOUND_PORT_DENIED")
    return True

def install():
    global _installed
    if _installed: return
    original_connect=socket.socket.connect
    original_connect_ex=socket.socket.connect_ex
    original_create=socket.create_connection
    original_getaddrinfo=socket.getaddrinfo
    original_socketpair=socket.socketpair

    def guarded_socketpair(*args,**kwargs):
        # Windows asyncio creates an internal socketpair via loopback ephemeral.
        # Permit ONLY the synchronous internal socketpair construction.
        _pair_internal.active=True
        try:return original_socketpair(*args,**kwargs)
        finally:_pair_internal.active=False

    @wraps(original_connect)
    def guarded_connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6) and not getattr(_pair_internal,"active",False):
            allow(address)
        return original_connect(sock,address)

    def guarded_connect_ex(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6) and not getattr(_pair_internal,"active",False):
            try:allow(address)
            except (PermissionError,ValueError,TypeError):return 13
        return original_connect_ex(sock,address)

    def guarded_create(address,*a,**kw):
        allow(address)
        return original_create(address,*a,**kw)

    def guarded_resolve(host,port,*a,**kw):
        if host not in ("localhost","127.0.0.1","::1",None):
            raise PermissionError("G3_TEST_EXTERNAL_DNS_DENIED")
        if port not in (None,55439,"55439"):
            raise PermissionError("G3_TEST_EXTERNAL_PORT_DENIED")
        return original_getaddrinfo(host,port,*a,**kw)

    socket.socket.connect=guarded_connect
    socket.socket.connect_ex=guarded_connect_ex
    socket.create_connection=guarded_create
    socket.getaddrinfo=guarded_resolve
    socket.socketpair=guarded_socketpair
    _installed=True
