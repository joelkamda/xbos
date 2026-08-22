from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from main import app as _inner_app

ERROR_FILE = Path(
    os.environ.get(
        "R6_3_UAT_ERROR_FILE",
        str(Path.home() / "Downloads" / "XBOS_R6_3_UAT_WORKSPACE" / "r6_3_uat_errors.jsonl"),
    )
)
ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)


def _safe_text(raw: bytes, limit: int = 20000) -> str:
    if len(raw) > limit:
        raw = raw[:limit] + b"\n...[truncated]..."
    return raw.decode("utf-8", errors="replace")


def _append(payload: dict[str, Any]) -> None:
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    # Open/write/flush/close for every record. The diagnostic file is never held
    # open by the UAT server, so reading it from CMD/Python cannot hang on an
    # inherited long-lived file handle.
    with ERROR_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        handle.flush()


class ObservedApp:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.inner(scope, receive, send)

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        query = (scope.get("query_string") or b"").decode("utf-8", errors="replace")
        status_code = None
        response_chunks: list[bytes] = []
        exception_recorded = False

        async def observed_send(message):
            nonlocal status_code
            mtype = message.get("type")
            if mtype == "http.response.start":
                status_code = int(message.get("status") or 0)
            elif mtype == "http.response.body":
                body = message.get("body") or b""
                if body and sum(len(x) for x in response_chunks) < 20000:
                    response_chunks.append(body)
            await send(message)

        try:
            return await self.inner(scope, receive, observed_send)
        except BaseException as exc:
            exception_recorded = True
            _append(
                {
                    "event": "exception",
                    "method": method,
                    "path": path,
                    "query": query,
                    "status_code": status_code,
                    "exception_type": type(exc).__name__,
                    "exception": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            raise
        finally:
            if status_code is not None and status_code >= 500:
                _append(
                    {
                        "event": "http_5xx",
                        "method": method,
                        "path": path,
                        "query": query,
                        "status_code": status_code,
                        "response_body": _safe_text(b"".join(response_chunks)),
                        "exception_propagated": exception_recorded,
                    }
                )


app = ObservedApp(_inner_app)
