from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.verify_r6_3_wnd_application_compatibility import WORKSPACE

PID_FILE = WORKSPACE / "r6_3_uat_runtime_pids.json"


def stop_pid(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


def main() -> int:
    if not PID_FILE.is_file():
        print("R6_3_UAT_RUNTIME_STOPPED=PASS")
        print("R6_3_UAT_PID_FILE=ABSENT")
        return 0

    payload = json.loads(PID_FILE.read_text(encoding="utf-8"))
    for key in ("frontend_pid", "backend_pid"):
        pid = payload.get(key)
        if pid:
            stop_pid(int(pid))
    PID_FILE.unlink(missing_ok=True)
    print("R6_3_UAT_RUNTIME_STOPPED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
