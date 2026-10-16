"""VN2-only ASGI fail-closed boundary, including when lifespan is disabled."""
import os

from vn2_staging_predeploy import check_database, security_config, target_url

_UNREADY = b'{"detail":"VN2_NOT_READY"}'
_delegate = None


async def app(scope, receive, send):
    global _delegate
    kind = scope.get("type")
    if kind == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    if kind not in ("http", "websocket"):
        return
    # PCR release is a separate governance decision. This flag alone cannot
    # supply PCR approval; missing or non-exact values deny customer traffic.
    if os.environ.get("XBOS_VN2_PUBLIC_RELEASE_AUTHORIZED") != "true":
        if kind == "http" and scope.get("path") == "/health":
            try:
                security_config()
                check_database(target_url(), ready=True)
            except Exception:
                pass
            else:
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b'{"status":"ready"}'})
                return
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": _UNREADY})
        return
    try:
        security_config()
        check_database(target_url(), ready=True)
        if _delegate is None:
            from main import app as original_app
            _delegate = original_app
    except Exception:
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": _UNREADY})
        return
    await _delegate(scope, receive, send)
