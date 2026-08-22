from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_3_wnd_application_compatibility as r63

WORKSPACE = r63.WORKSPACE
PID_FILE = WORKSPACE / "r6_3_uat_runtime_pids.json"
BACKEND_LOG = WORKSPACE / "r6_3_uat_backend.log"
FRONTEND_LOG = WORKSPACE / "r6_3_uat_frontend.log"
ERROR_FILE = WORKSPACE / "r6_3_uat_errors.jsonl"

BACKEND_PORT = 8002
FRONTEND_PORT = 5174


def _port_free(port: int) -> bool:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _tail(path: Path, lines: int = 80) -> str:
    if not path.is_file():
        return "<log not created>"
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = text.splitlines()
    return "\n".join(rows[-lines:])


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except Exception:
        return False


def _terminate(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    # Revalidate the exact already-accepted automated result and candidate.
    r63._uat_ready()

    if not _port_free(BACKEND_PORT):
        raise RuntimeError(f"R6_3_BACKEND_PORT_{BACKEND_PORT}_IN_USE")
    if not _port_free(FRONTEND_PORT):
        raise RuntimeError(f"R6_3_FRONTEND_PORT_{FRONTEND_PORT}_IN_USE")

    backend_dir = WORKSPACE / "backend"
    frontend_dir = WORKSPACE / "frontend"
    vite_config = frontend_dir / "vite.r6-3-uat.config.ts"
    if not backend_dir.is_dir():
        raise RuntimeError("R6_3_UAT_BACKEND_WORKSPACE_MISSING")
    if not frontend_dir.is_dir():
        raise RuntimeError("R6_3_UAT_FRONTEND_WORKSPACE_MISSING")
    if not vite_config.is_file():
        raise RuntimeError("R6_3_UAT_VITE_CONFIG_MISSING")

    node = shutil.which("node.exe") or shutil.which("node")
    if not node:
        raise RuntimeError("R6_3_NODE_NOT_FOUND_IN_UAT_RUNTIME")

    vite_js = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_js.is_file():
        raise RuntimeError("R6_3_VITE_JS_NOT_FOUND_IN_UAT_RUNTIME")

    for log_path in (BACKEND_LOG, FRONTEND_LOG, ERROR_FILE):
        if log_path.exists():
            log_path.unlink()

    observer_template = ROOT / "scripts/r6_3_uat_host_template.py"
    observer_host = backend_dir / "r6_3_uat_host.py"
    if not observer_template.is_file():
        raise RuntimeError("R6_3_UAT_OBSERVER_TEMPLATE_MISSING")
    shutil.copy2(observer_template, observer_host)

    backend_handle = BACKEND_LOG.open("w", encoding="utf-8", errors="replace")
    frontend_handle = FRONTEND_LOG.open("w", encoding="utf-8", errors="replace")
    backend_proc = None
    frontend_proc = None

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        # Start the backend exactly the same way the already-green automated
        # runtime smoke did: exact frozen WND backend, candidate DB, uvicorn 8002.
        backend_proc = subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "uvicorn",
                "r6_3_uat_host:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=backend_dir,
            env={**r63._backend_env(), "R6_3_UAT_ERROR_FILE": str(ERROR_FILE)},
            stdout=backend_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        deadline = time.time() + 60
        while time.time() < deadline:
            if _http_ok(f"http://127.0.0.1:{BACKEND_PORT}/health"):
                break
            if backend_proc.poll() is not None:
                raise RuntimeError(
                    "R6_3_UAT_BACKEND_EXITED_EARLY\n"
                    + _tail(BACKEND_LOG)
                )
            time.sleep(1)
        else:
            raise RuntimeError(
                "R6_3_UAT_BACKEND_HEALTH_TIMEOUT\n"
                + _tail(BACKEND_LOG)
            )

        # Launch Vite through node.exe directly rather than through npm.cmd.
        # On Windows, npm.cmd may hand off to a Node child and return, which
        # makes Popen.poll() look like a failed frontend even while Vite is
        # already listening. Tracking the actual Node/Vite process removes that
        # wrapper ambiguity.
        frontend_proc = subprocess.Popen(
            [
                node,
                str(vite_js),
                "--config",
                "vite.r6-3-uat.config.ts",
                "--host",
                "127.0.0.1",
                "--port",
                str(FRONTEND_PORT),
            ],
            cwd=frontend_dir,
            env=os.environ.copy(),
            stdout=frontend_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        deadline = time.time() + 60
        while time.time() < deadline:
            if _http_ok(f"http://127.0.0.1:{FRONTEND_PORT}/"):
                break
            if frontend_proc.poll() is not None:
                raise RuntimeError(
                    "R6_3_UAT_FRONTEND_EXITED_EARLY\n"
                    + _tail(FRONTEND_LOG)
                )
            time.sleep(1)
        else:
            raise RuntimeError(
                "R6_3_UAT_FRONTEND_HEALTH_TIMEOUT\n"
                + _tail(FRONTEND_LOG)
            )

        PID_FILE.write_text(
            json.dumps(
                {
                    "backend_pid": backend_proc.pid,
                    "frontend_pid": frontend_proc.pid,
                    "backend_port": BACKEND_PORT,
                    "frontend_port": FRONTEND_PORT,
                    "database": r63.CANDIDATE_DATABASE,
                    "backend_log": str(BACKEND_LOG),
                    "frontend_log": str(FRONTEND_LOG),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        print("============================================================")
        print("R6_3_UAT_RUNTIME=PASS")
        print(f"FRONTEND=http://127.0.0.1:{FRONTEND_PORT}")
        print(f"BACKEND=http://127.0.0.1:{BACKEND_PORT}")
        print(f"DATABASE={r63.CANDIDATE_DATABASE}")
        print(f"BACKEND_PID={backend_proc.pid}")
        print(f"FRONTEND_PID={frontend_proc.pid}")
        print(f"BACKEND_LOG={BACKEND_LOG}")
        print(f"FRONTEND_LOG={FRONTEND_LOG}")
        print(f"ERROR_LOG={ERROR_FILE}")
        print("PRODUCTION_WRITES=NONE")
        print("PRODUCTION_WRITER_ROUTING=UNCHANGED")
        print("LIVE_CUTOVER_AUTHORIZED=NO")
        print("============================================================")
        return 0
    except Exception:
        _terminate(frontend_proc)
        _terminate(backend_proc)
        raise
    finally:
        backend_handle.close()
        frontend_handle.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("============================================================")
        print("R6_3_UAT_RUNTIME=FAIL")
        print(str(exc))
        if BACKEND_LOG.is_file():
            print("----- BACKEND LOG TAIL -----")
            print(_tail(BACKEND_LOG))
        if FRONTEND_LOG.is_file():
            print("----- FRONTEND LOG TAIL -----")
            print(_tail(FRONTEND_LOG))
        print("============================================================")
        raise SystemExit(1)
