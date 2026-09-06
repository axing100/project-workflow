#!/usr/bin/env python3
"""Run all native suites with durable timings and no failure short-circuit.

@author chenjiaxing
@since 2026-09-04
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    """Collect actual host evidence without claiming another OS was tested."""
    root = Path(__file__).resolve().parents[1]
    output = root / "platform-evidence"
    output.mkdir(exist_ok=True)
    commands = {
        "plugin-tests": ["-m", "unittest", "discover", "-s", "plugins/project-workflow/tests", "-v"],
        "installer-tests": ["-m", "unittest", "discover", "-s", "tests", "-v"],
        "compile": ["-m", "compileall", "-q", "plugins/project-workflow", "scripts", "tests"],
        "doctor": ["plugins/project-workflow/scripts/project_workflow_doctor.py", "--repo", str(root), "--json"],
    }
    results = []
    for name, arguments in commands.items():
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, *arguments], cwd=root, capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=600, check=False)
            code, log = result.returncode, result.stdout + result.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, log = 2, str(exc)
        elapsed = round(time.monotonic() - started, 3)
        (output / (name + ".log")).write_text(log, encoding="utf-8")
        print(f"{name}: exit={code}, seconds={elapsed}", flush=True)
        if code:
            print(log, flush=True)
        results.append({"suite": name, "exit_code": code, "seconds": elapsed})
    report = {"os": platform.platform(), "python": sys.version, "results": results,
              "desktop_host_verified": False}
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 1 if any(result["exit_code"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
