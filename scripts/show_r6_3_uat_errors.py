from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_r6_3_wnd_application_compatibility import WORKSPACE

ERROR_FILE = WORKSPACE / "r6_3_uat_errors.jsonl"


def main() -> int:
    print(f"R6_3_UAT_ERROR_FILE={ERROR_FILE}")
    if not ERROR_FILE.is_file():
        print("R6_3_UAT_ERROR_RECORDS=0")
        print("No captured UAT 5xx/exception evidence exists yet.")
        return 0

    rows = []
    for raw in ERROR_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rows.append(json.loads(raw))
        except Exception:
            rows.append({"event": "unparseable", "raw": raw})

    print(f"R6_3_UAT_ERROR_RECORDS={len(rows)}")
    for index, row in enumerate(rows[-12:], start=max(1, len(rows) - 11)):
        print()
        print("=" * 72)
        print(f"R6_3_UAT_ERROR_RECORD={index}")
        print(f"EVENT={row.get('event')}")
        print(f"METHOD={row.get('method')}")
        print(f"PATH={row.get('path')}")
        print(f"STATUS={row.get('status_code')}")
        if row.get("exception_type"):
            print(f"EXCEPTION_TYPE={row.get('exception_type')}")
        if row.get("exception"):
            print(f"EXCEPTION={row.get('exception')}")
        if row.get("response_body"):
            print("RESPONSE_BODY:")
            print(row.get("response_body"))
        if row.get("traceback"):
            print("TRACEBACK:")
            print(row.get("traceback"))
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
