"""Black-box tests for the isolated local plugin installer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/install_local_plugin.py"
SPEC = importlib.util.spec_from_file_location("install_local_plugin", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class LocalInstallerTest(unittest.TestCase):
    """Verify cache metadata stays inside the disposable staging copy."""

    def create_repository(self, root: Path, version: str = "0.4.0") -> Path:
        """Create the minimal marketplace layout required by the installer."""
        repo_root = root / "repo"
        plugin_root = repo_root / "plugins/project-workflow"
        manifest_path = plugin_root / ".codex-plugin/plugin.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({"name": "project-workflow", "version": version}),
            encoding="utf-8",
        )
        marketplace_path = repo_root / ".agents/plugins/marketplace.json"
        marketplace_path.parent.mkdir(parents=True)
        marketplace_path.write_text(
            json.dumps({"name": "project-workflow-local", "plugins": []}),
            encoding="utf-8",
        )
        return repo_root

    def test_staging_copy_gets_cachebuster_without_changing_source(self) -> None:
        """The staged manifest changes while the source manifest remains byte-identical."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = self.create_repository(root)
            source_manifest = (
                repo_root
                / "plugins/project-workflow/.codex-plugin/plugin.json"
            )
            original_bytes = source_manifest.read_bytes()
            staging_root = root / "staging"

            version = INSTALLER.create_staging_marketplace(
                repo_root,
                staging_root,
                "test-20260825",
            )

            staged_manifest = INSTALLER.load_json(
                staging_root
                / "plugins/project-workflow/.codex-plugin/plugin.json"
            )
            self.assertEqual("0.4.0+codex.test-20260825", version)
            self.assertEqual(version, staged_manifest["version"])
            self.assertEqual(original_bytes, source_manifest.read_bytes())

    def test_release_manifest_rejects_existing_build_metadata(self) -> None:
        """A dirty source version fails before installation starts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = self.create_repository(
                root,
                "0.4.0+codex.old",
            )

            with self.assertRaisesRegex(ValueError, "clean release version"):
                INSTALLER.create_staging_marketplace(
                    repo_root,
                    root / "staging",
                    "next",
                )

    def test_default_cachebuster_is_unique_and_semver_safe(self) -> None:
        """Avoid collisions between multiple local installs in the same second."""
        with patch.object(INSTALLER.secrets, "token_hex", side_effect=("a1b2c3d4", "e5f60718")):
            first = INSTALLER.default_cachebuster()
            second = INSTALLER.default_cachebuster()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9]{20}-[0-9a-f]{8}$")
        self.assertRegex(second, r"^[0-9]{20}-[0-9a-f]{8}$")
        self.assertIsNotNone(
            INSTALLER.SEMVER_PATTERN.fullmatch(f"0.4.0+codex.{first}")
        )

    def test_invalid_release_semver_is_rejected(self) -> None:
        """Do not generate a cache version from an invalid source release."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = self.create_repository(root, "v0.4")
            with self.assertRaisesRegex(ValueError, "valid SemVer"):
                INSTALLER.create_staging_marketplace(
                    repo_root,
                    root / "staging",
                    "next",
                )

    def test_install_temporarily_swaps_and_restores_marketplace(self) -> None:
        """Installation restores the original marketplace after using staging."""
        staging_root = Path("/tmp/project-workflow-stage")
        repo_root = Path("/tmp/project-workflow-source").resolve()
        commands: list[tuple[str, ...]] = []

        def fake_run(codex_bin: str, *arguments: str):
            commands.append((codex_bin, *arguments))
            if arguments == ("plugin", "marketplace", "list"):
                return INSTALLER.subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=(
                        "MARKETPLACE ROOT\n"
                        f"project-workflow-local {repo_root}\n"
                    ),
                    stderr="",
                )
            return INSTALLER.subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr="",
            )

        with patch.object(INSTALLER, "run_codex", side_effect=fake_run):
            INSTALLER.install_staged_plugin(
                "codex-test",
                staging_root,
                repo_root,
            )

        self.assertEqual(
            [
                ("codex-test", "plugin", "marketplace", "list"),
                (
                    "codex-test",
                    "plugin",
                    "marketplace",
                    "remove",
                    "project-workflow-local",
                ),
                (
                    "codex-test",
                    "plugin",
                    "marketplace",
                    "add",
                    str(staging_root),
                ),
                (
                    "codex-test",
                    "plugin",
                    "add",
                    "project-workflow@project-workflow-local",
                ),
                (
                    "codex-test",
                    "plugin",
                    "marketplace",
                    "remove",
                    "project-workflow-local",
                ),
                (
                    "codex-test",
                    "plugin",
                    "marketplace",
                    "add",
                    str(repo_root),
                ),
            ],
            commands,
        )

    def test_install_restores_marketplace_when_plugin_add_fails(self) -> None:
        """The original marketplace returns even when installation is interrupted."""
        staging_root = Path("/tmp/project-workflow-stage")
        repo_root = Path("/tmp/project-workflow-source").resolve()
        commands: list[tuple[str, ...]] = []

        def fake_run(codex_bin: str, *arguments: str):
            commands.append((codex_bin, *arguments))
            if arguments == ("plugin", "marketplace", "list"):
                return INSTALLER.subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=f"project-workflow-local {repo_root}\n",
                    stderr="",
                )
            if arguments[:2] == ("plugin", "add"):
                raise INSTALLER.subprocess.CalledProcessError(1, arguments)
            return INSTALLER.subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr="",
            )

        with patch.object(INSTALLER, "run_codex", side_effect=fake_run):
            with self.assertRaises(INSTALLER.subprocess.CalledProcessError):
                INSTALLER.install_staged_plugin(
                    "codex-test",
                    staging_root,
                    repo_root,
                )

        self.assertEqual(
            (
                "codex-test",
                "plugin",
                "marketplace",
                "add",
                str(repo_root),
            ),
            commands[-1],
        )

    def test_restore_is_attempted_when_temporary_cleanup_fails(self) -> None:
        """Always restore the source marketplace even when staging removal fails."""
        staging_root = Path("/tmp/project-workflow-stage")
        repo_root = Path("/tmp/project-workflow-source").resolve()
        commands: list[tuple[str, ...]] = []
        remove_count = 0

        def fake_run(codex_bin: str, *arguments: str):
            nonlocal remove_count
            commands.append((codex_bin, *arguments))
            if arguments == ("plugin", "marketplace", "list"):
                return INSTALLER.subprocess.CompletedProcess(
                    [], 0, stdout=f"project-workflow-local {repo_root}\n", stderr=""
                )
            if arguments[:3] == ("plugin", "marketplace", "remove"):
                remove_count += 1
                if remove_count == 2:
                    raise INSTALLER.subprocess.CalledProcessError(1, arguments)
            return INSTALLER.subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch.object(INSTALLER, "run_codex", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "temporary marketplace cleanup failed"):
                INSTALLER.install_staged_plugin("codex-test", staging_root, repo_root)

        self.assertEqual(
            ("codex-test", "plugin", "marketplace", "add", str(repo_root)),
            commands[-1],
        )

    def test_restore_failure_is_reported_explicitly(self) -> None:
        """Surface an unrecovered marketplace instead of reporting only install failure."""
        staging_root = Path("/tmp/project-workflow-stage")
        repo_root = Path("/tmp/project-workflow-source").resolve()

        def fake_run(codex_bin: str, *arguments: str):
            if arguments == ("plugin", "marketplace", "list"):
                return INSTALLER.subprocess.CompletedProcess(
                    [], 0, stdout=f"project-workflow-local {repo_root}\n", stderr=""
                )
            if arguments == ("plugin", "marketplace", "add", str(repo_root)):
                raise INSTALLER.subprocess.CalledProcessError(1, arguments)
            return INSTALLER.subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch.object(INSTALLER, "run_codex", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "failed to restore"):
                INSTALLER.install_staged_plugin("codex-test", staging_root, repo_root)


if __name__ == "__main__":
    unittest.main()
