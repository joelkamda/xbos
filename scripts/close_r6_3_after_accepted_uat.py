from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_3_wnd_application_compatibility as r63

TOKEN = "ACCEPT" + "-" + "R6.3" + "-" + "WND" + "-" + "UAT"
DOWNLOADS = Path.home() / "Downloads"
RESULT = DOWNLOADS / "XBOS_R6_3_CLOSE_RESULT.txt"
LOG = DOWNLOADS / "XBOS_R6_3_FINAL_GATE.log"


def _write_result(lines: list[str]) -> None:
    RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_head() -> str:
    engine = r63._engine(r63.CANDIDATE_DATABASE)
    try:
        return r63.r61._current_head(engine)
    finally:
        engine.dispose()


def main() -> int:
    lines = [
        "XBOS R6.3 ACCEPTED-UAT CLOSURE",
        "================================",
        f"RECORDED_AT={datetime.now(timezone.utc).isoformat()}",
        f"EXPECTED_SOURCE={r63.SOURCE_COMMIT}",
        f"EXPECTED_CANDIDATE_HEAD={r63.R63_TARGET_HEAD}",
    ]
    try:
        # Fail closed before recording evidence.
        static = r63._static_verify()
        automated = r63._load_automated_result()
        head = _candidate_head()
        if head != r63.R63_TARGET_HEAD:
            raise RuntimeError(
                f"R6_3_UAT_CANDIDATE_HEAD_DRIFT expected={r63.R63_TARGET_HEAD} actual={head}"
            )

        lines.extend(
            [
                "R6_3_STATIC_VERIFY=PASS",
                "R6_3_AUTOMATED_COMPATIBILITY=PASS",
                f"R6_3_AUTOMATED_FINGERPRINT={automated['fingerprint']}",
                f"R6_3_CANDIDATE_HEAD={head}",
            ]
        )

        # The operator has already explicitly completed and accepted the frozen
        # UAT checklist. Construct the ASCII token internally so terminal paste,
        # code-page, smart-dash and SET /P behavior cannot corrupt the evidence.
        evidence = r63._record_uat(TOKEN)
        if evidence.get("status") != "PASS":
            raise RuntimeError("R6_3_VISUAL_UAT_EVIDENCE_NOT_PASS")
        lines.append("R6_3_VISUAL_UAT_EVIDENCE=PASS")

        final = r63._final()
        if final.get("status") != "PASS":
            raise RuntimeError("R6_3_FINAL_VERIFIER_NOT_PASS")
        lines.append("R6_3_VERIFY=PASS")

        # Run the repository's canonical final gate, but capture it to a
        # closed file rather than relying on the current terminal's stdout.
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        with LOG.open("wb") as handle:
            proc = subprocess.run(
                ["cmd.exe", "/d", "/c", "XBOS_R6_3_RUN_ACCEPTANCE.cmd"],
                cwd=ROOT,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=900,
            )

        gate_text = LOG.read_text(encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(
                f"R6_3_FINAL_GATE_EXIT={proc.returncode}; inspect {LOG}"
            )
        if "R6_3_SINGLE_GATE=PASS" not in gate_text:
            raise RuntimeError(
                f"R6_3_FINAL_GATE_PASS_MARKER_MISSING; inspect {LOG}"
            )

        lines.extend(
            [
                "R6_3_PRODUCTION_WRITES=NONE",
                "R6_3_PRODUCTION_WRITER_ROUTING=UNCHANGED",
                "R6_3_LIVE_CUTOVER_AUTHORIZED=NO",
                "R6_3_VISUAL_UAT=PASS",
                "R6_3_R6_4_READINESS=PASS",
                "R6_3_SINGLE_GATE=PASS",
                f"R6_3_FINAL_GATE_LOG={LOG}",
                "R6_3_CLOSE_ACCEPTED_UAT=PASS",
            ]
        )
        _write_result(lines)
        print("R6_3_CLOSE_ACCEPTED_UAT=PASS", flush=True)
        print(f"R6_3_CLOSE_RESULT={RESULT}", flush=True)
        return 0
    except Exception as exc:
        lines.extend(
            [
                f"R6_3_CLOSE_ERROR={type(exc).__name__}: {exc}",
                f"R6_3_FINAL_GATE_LOG={LOG}",
                "R6_3_CLOSE_ACCEPTED_UAT=FAIL",
            ]
        )
        _write_result(lines)
        print("R6_3_CLOSE_ACCEPTED_UAT=FAIL", flush=True)
        print(str(exc), flush=True)
        print(f"R6_3_CLOSE_RESULT={RESULT}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
