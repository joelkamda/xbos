from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_3_wnd_application_compatibility as r63


def main() -> int:
    r63._uat_ready()
    backend = r63.WORKSPACE / "backend"
    env = r63._backend_env()
    print("R6_3_REFERENCE_BACKEND_DATABASE=xbos_r6_3_candidate", flush=True)
    print("R6_3_REFERENCE_BACKEND_PORT=8002", flush=True)
    return subprocess.call(
        [sys.executable, "-X", "utf8", "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8002"],
        cwd=backend,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
