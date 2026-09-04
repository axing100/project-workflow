"""Opt-in real Codex CLI installation, isolated from personal configuration.

@author chenjiaxing
@since 2026-09-05
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("real_install_helper", ROOT / "scripts/install_local_plugin.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


@unittest.skipUnless(os.environ.get("PROJECT_WORKFLOW_CODEX_ROOT") or os.environ.get("PROJECT_WORKFLOW_CODEX_BIN"), "explicit real CLI path required; CI enables this suite")
class RealInstallTest(unittest.TestCase):
    """Install and update through the public CLI without touching personal state.

    @author chenjiaxing
    @since 2026-09-05
    """

    def test_install_update_restore(self):
        """Verify real CLI cache contents, update and original marketplace restore."""
        if os.environ.get("PROJECT_WORKFLOW_CODEX_BIN"):
            executable = Path(os.environ["PROJECT_WORKFLOW_CODEX_BIN"])
        else:
            prefix = Path(os.environ["PROJECT_WORKFLOW_CODEX_ROOT"])
            executable = prefix / ("codex.cmd" if os.name == "nt" else "bin/codex")
        command = INSTALLER.codex_command(str(executable))
        manifest = ROOT / "plugins/project-workflow/.codex-plugin/plugin.json"
        original = manifest.read_bytes()
        with tempfile.TemporaryDirectory(prefix="workflow-real-cli-") as temporary:
            isolated = Path(temporary) / "codex-config"
            isolated.mkdir()
            environment = dict(os.environ, CODEX_HOME=str(isolated), PYTHONUTF8="1")
            added = subprocess.run([*command, "plugin", "marketplace", "add", str(ROOT)],
                                   env=environment, capture_output=True, encoding="utf-8", timeout=60)
            self.assertEqual(0, added.returncode, added.stdout + added.stderr)
            for token in ("native-first", "native-update"):
                installed = subprocess.run([sys.executable, str(ROOT / "scripts/install_local_plugin.py"),
                                            "--repo-root", str(ROOT), "--codex-bin", str(executable),
                                            "--cachebuster", token], env=environment,
                                           capture_output=True, encoding="utf-8", timeout=90)
                self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
                self.assertEqual(original, manifest.read_bytes())
                cached = list(isolated.glob("plugins/cache/**/.codex-plugin/plugin.json"))
                self.assertTrue(any(json.loads(path.read_text(encoding="utf-8")).get("version", "").endswith(token)
                                    for path in cached), installed.stdout)
            restored = subprocess.run([*command, "plugin", "marketplace", "list"],
                                      env=environment, capture_output=True, encoding="utf-8", timeout=60)
            self.assertEqual(0, restored.returncode, restored.stderr)
            self.assertIn("project-workflow-local", restored.stdout)
            self.assertIn(str(ROOT), restored.stdout)


if __name__ == "__main__":
    unittest.main()
