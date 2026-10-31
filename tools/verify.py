#!/usr/bin/env python3
"""Run the offline acceptance checks and retain exact commands and logs."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/verification"
OUT.mkdir(parents=True, exist_ok=True)
checks = [
    ("init", ["tools/research.py", "init"], 0),
    ("init-idempotent", ["tools/research.py", "init"], 0),
    ("doctor", ["tools/research.py", "doctor"], 0),
    ("offline-config", ["tools/research.py", "validate"], 0),
    ("toy-computation", ["tools/research.py", "smoke"], 0),
    ("project-behavior", ["-m", "unittest", "discover", "-s", "tests", "-v"], 0),
    ("upstream-inventory", ["vendor/aris/tools/check_skills_inventory.py"], 0),
    ("upstream-state-tests", ["tools/verify_upstream.py"], 0),
    ("real-config-blocked", ["tools/research.py", "validate", "--real"], 2),
    ("baseline-preflight-blocked", ["tools/research.py", "baseline-preflight"], 2),
    ("paper-empty-evidence", ["tools/research.py", "audit", "--paper"], 0),
    ("recovery-no-submit", ["tools/research.py", "resume"], 0),
]
results = []
for name, arguments, expected in checks:
    command = [sys.executable, *arguments]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    logfile = OUT / f"{name}.log"
    logfile.write_text(run.stdout + run.stderr, encoding="utf-8")
    passed = run.returncode == expected
    results.append({"name": name, "command": command, "cwd": str(ROOT),
                    "exit_code": run.returncode, "expected_exit_code": expected,
                    "status": "PASS" if passed else "FAIL", "log": logfile.relative_to(ROOT).as_posix()})
    print(f"{name}: {'PASS' if passed else 'FAIL'} (exit {run.returncode}, expected {expected})", flush=True)
report = {"status": "PASS" if all(x["status"] == "PASS" for x in results) else "FAIL",
          "at": datetime.now(timezone.utc).isoformat(), "scope": "offline engineering only",
          "checks": results,
          "unverified": ["real baseline/data/GPU", "external model/CLI/API/MCP calls and actual identity verification",
                         "remote tmux or scheduler", "external model payments and cloud billing",
                         "other upstream pytest suites (pytest unavailable)", "scientific novelty, effect size and paper claims"],
          "note": "Empty paper evidence and blocked real stages are expected; neither is scientific acceptance."}
(OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
raise SystemExit(0 if report["status"] == "PASS" else 1)
