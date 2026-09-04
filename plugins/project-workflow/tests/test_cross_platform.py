"""Native Unicode, long-path and non-UTF-8 CLI contracts.

@author chenjiaxing
@since 2026-09-05
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class CrossPlatformTest(unittest.TestCase):
    """Exercise public commands on the actual host, not mocked OS branches.

    @author chenjiaxing
    @since 2026-09-05
    """

    def run_cli(self, script, *arguments, expected=0):
        """Force a legacy output encoding while decoding the public UTF-8 API."""
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="ascii")
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                                env=environment, capture_output=True, encoding="utf-8",
                                errors="strict", timeout=30, check=False)
        self.assertEqual(expected, result.returncode, result.stderr + result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_all_cli_imports(self):
        """Every public entry point must load on the real target platform."""
        for script in ("workflow_state.py", "orchestration_state.py", "task_state.py",
                       "filesystem_snapshot.py", "project_workflow_doctor.py"):
            with self.subTest(script=script):
                self.run_cli(script, "--help")

    @unittest.skipUnless(os.name == "nt", "Windows legacy console encoding contract")
    def test_unicode_plan_roundtrip(self):
        """Preserve Chinese state through real Windows subprocesses and locks."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文 工作区"
            root.mkdir()
            plan = root / "中文计划.md"
            plan.write_text("# 中文计划\n", encoding="utf-8")
            self.run_cli("workflow_state.py", "init", plan, "--repo", root,
                         "--plan-id", "unicode", "--vcs-mode", "NONE")
            self.assertIn("unicode", plan.read_text(encoding="utf-8"))
            result = self.run_cli("project_workflow_doctor.py", "--repo", root, "--json")
            self.assertEqual("OK", json.loads(result.stdout)["status"])

    @unittest.skipUnless(os.name == "nt", "Windows extended-length path contract")
    def test_long_path_snapshot_roundtrip(self):
        """Create and read real evidence with a workspace path beyond MAX_PATH."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(8):
                root = root / ("segment-" + str(index) + "-" + "x" * 30)
            root.mkdir(parents=True)
            (root / "payload.txt").write_text("long path", encoding="utf-8")
            output = ".codex/project-workflow/long/baseline.json"
            self.run_cli("filesystem_snapshot.py", "create", "--repo", root, "--output", output)
            self.run_cli("filesystem_snapshot.py", "compare", "--repo", root, "--baseline", output)


if __name__ == "__main__":
    unittest.main()
