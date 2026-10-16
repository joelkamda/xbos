"""VN2-only ASGI fail-closed boundary, including when lifespan is disabled."""
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
