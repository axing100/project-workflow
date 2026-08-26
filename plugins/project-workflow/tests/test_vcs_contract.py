"""Independent black-box tests for the Git-optional workflow contract."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins/project-workflow"
DOCTOR = PLUGIN_ROOT / "scripts/project_workflow_doctor.py"
WORKFLOW_STATE = PLUGIN_ROOT / "scripts/workflow_state.py"
FILESYSTEM_SNAPSHOT = PLUGIN_ROOT / "scripts/filesystem_snapshot.py"


class VcsContractTest(unittest.TestCase):
    """Verify public VCS behavior without importing implementation modules."""

    def run_script(
        self,
        script: Path,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a public helper exactly as a caller would."""
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def doctor(
        self,
        repository: Path,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        """Run Doctor in its stable JSON mode."""
        result = self.run_script(
            DOCTOR,
            "--repo",
            str(repository),
            *arguments,
            "--json",
            env=env,
        )
        return result, json.loads(result.stdout)

    @staticmethod
    def write_plan(
        path: Path,
        *,
        profile: str = "LIGHT",
        phase: str = "IN_PROGRESS",
        vcs_mode: str | None = "NONE",
        resolved_vcs_mode: str | None = "NONE",
        rollback_strategy: str | None = None,
        rollback_evidence: str | None = None,
        rollback_verification: str | None = None,
    ) -> None:
        """Write a minimal public project-workflow/v1 plan fixture."""
        approved_revision = "1" if phase in {"APPROVED", "IN_PROGRESS"} else ""
        approved_at = '"2026-08-25T00:00:00+00:00"' if approved_revision else ""
        confirmation = '"同意"' if approved_revision else ""
        fields = [
            'workflow: "project-workflow/v1"',
            'plan_id: "black-box-contract"',
            "revision: 1",
            f'phase: "{phase}"',
            f'workflow_profile: "{profile}"',
            f"approved_revision: {approved_revision}",
            f"approved_at: {approved_at}",
            f"confirmation_record: {confirmation}",
            'conversation_title: "Black-box contract"',
            "progress_heartbeat_minutes: 5",
        ]
        optional_fields = (
            ("vcs_mode", vcs_mode),
            ("resolved_vcs_mode", resolved_vcs_mode),
            ("rollback_strategy", rollback_strategy),
            ("rollback_evidence", rollback_evidence),
            ("rollback_verification", rollback_verification),
        )
        for key, value in optional_fields:
            if value is not None:
                fields.append(f'{key}: "{value}"')
        path.write_text("---\n" + "\n".join(fields) + "\n---\n\n# Plan\n", encoding="utf-8")

    @staticmethod
    def init_git(repository: Path) -> None:
        """Initialize an isolated disposable worktree for black-box detection."""
        if shutil.which("git") is None:
            raise unittest.SkipTest("Git is unavailable for the disposable worktree case")
        result = subprocess.run(
            ["git", "init", "--quiet", str(repository)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)

    def test_auto_non_git_directory_resolves_none(self) -> None:
        """AUTO remains usable in an ordinary directory that is not a worktree."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result, report = self.doctor(repository, "--vcs-mode", "AUTO")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("OK", report["status"])
            self.assertEqual(
                {
                    "requested": "AUTO",
                    "resolved": "NONE",
                    "git_worktree": False,
                    "status": "OK",
                },
                {
                    key: report["version_control"][key]
                    for key in ("requested", "resolved", "git_worktree", "status")
                },
            )

    def test_missing_git_is_none_for_auto_and_blocker_for_explicit_git(self) -> None:
        """An absent Git executable is a supported AUTO result but violates GIT."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            empty_path = Path(temporary) / "empty-path"
            repository.mkdir()
            empty_path.mkdir()
            environment = os.environ.copy()
            environment["PATH"] = str(empty_path)

            auto_result, auto_report = self.doctor(repository, env=environment)
            git_result, git_report = self.doctor(
                repository,
                "--vcs-mode",
                "GIT",
                env=environment,
            )

            self.assertEqual(0, auto_result.returncode, auto_result.stderr)
            self.assertFalse(auto_report["version_control"]["git_available"])
            self.assertEqual("NONE", auto_report["version_control"]["resolved"])
            self.assertEqual(2, git_result.returncode)
            self.assertEqual("BLOCKED", git_report["status"])
            self.assertEqual("GIT", git_report["version_control"]["requested"])
            self.assertIsNone(git_report["version_control"]["resolved"])
            self.assertIn(
                "VCS_MODE_INVALID",
                {issue["code"] for issue in git_report["issues"]},
            )

    def test_explicit_none_does_not_invoke_git_inside_worktree(self) -> None:
        """NONE must not execute Git even when the directory is a worktree."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            self.init_git(repository)
            fake_bin = Path(temporary) / "fake-bin"
            fake_bin.mkdir()
            invocation_marker = Path(temporary) / "git-was-invoked"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                f"#!/bin/sh\nprintf invoked > '{invocation_marker}'\nexit 99\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin)

            result, report = self.doctor(
                repository,
                "--vcs-mode",
                "NONE",
                env=environment,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("NONE", report["version_control"]["resolved"])
            self.assertFalse(invocation_marker.exists())

    def test_explicit_git_non_worktree_blocks_without_partial_state(self) -> None:
        """A failed explicit GIT probe does not leave workflow state behind."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result, report = self.doctor(repository, "--vcs-mode", "GIT")

            self.assertEqual(2, result.returncode)
            self.assertEqual("BLOCKED", report["status"])
            self.assertFalse((repository / ".codex/project-workflow").exists())
            self.assertEqual([], list(repository.iterdir()))

    def test_auto_resolution_drift_blocks_in_both_directions(self) -> None:
        """Persisted AUTO resolution cannot silently change its evidence model."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            git_repository = base / "git-repo"
            git_repository.mkdir()
            self.init_git(git_repository)
            none_plan = git_repository / "plan.md"
            self.write_plan(
                none_plan,
                vcs_mode="AUTO",
                resolved_vcs_mode="NONE",
            )

            none_result, none_report = self.doctor(
                git_repository,
                "--plan",
                none_plan.name,
            )

            plain_repository = base / "plain-repo"
            plain_repository.mkdir()
            git_plan = plain_repository / "plan.md"
            self.write_plan(
                git_plan,
                vcs_mode="AUTO",
                resolved_vcs_mode="GIT",
            )
            git_result, git_report = self.doctor(
                plain_repository,
                "--plan",
                git_plan.name,
            )

            for result, report in (
                (none_result, none_report),
                (git_result, git_report),
            ):
                self.assertEqual(2, result.returncode)
                self.assertEqual("BLOCKED", report["status"])
                self.assertIn(
                    "VCS_ENVIRONMENT_DRIFT",
                    {issue["code"] for issue in report["issues"]},
                )

    def test_full_none_execution_requires_all_three_rollback_fields(self) -> None:
        """FULL/NONE entry blocks until all rollback evidence fields are valid."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            plan = repository / "plan.md"
            cases = (
                (None, "snapshot://known-good", "VERIFIED"),
                ("restore the snapshot", None, "VERIFIED"),
                ("restore the snapshot", "snapshot://known-good", None),
                ("restore the snapshot", "snapshot://known-good", "PENDING"),
            )
            for strategy, evidence, verification in cases:
                with self.subTest(
                    strategy=strategy,
                    evidence=evidence,
                    verification=verification,
                ):
                    self.write_plan(
                        plan,
                        profile="FULL",
                        phase="APPROVED",
                        rollback_strategy=strategy,
                        rollback_evidence=evidence,
                        rollback_verification=verification,
                    )
                    before = plan.read_bytes()
                    result = self.run_script(
                        WORKFLOW_STATE,
                        "start-execution",
                        str(plan),
                        "--confirmation",
                        "同意",
                        "--repo",
                        str(repository),
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(before, plan.read_bytes())

            self.write_plan(
                plan,
                profile="FULL",
                phase="APPROVED",
                rollback_strategy="restore the snapshot",
                rollback_evidence="snapshot://known-good",
                rollback_verification="VERIFIED",
            )
            result = self.run_script(
                WORKFLOW_STATE,
                "check-execute",
                str(plan),
                "--repo",
                str(repository),
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_snapshot_reports_changes_and_literal_scope_violations(self) -> None:
        """Snapshot comparison deterministically reports all change categories."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            allowed = repository / "allowed"
            allowed.mkdir()
            modified = allowed / "modified.txt"
            deleted = allowed / "deleted.txt"
            modified.write_text("before", encoding="utf-8")
            deleted.write_text("delete me", encoding="utf-8")
            baseline = repository / ".codex/project-workflow/test/baseline.json"

            first = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "create",
                "--repo",
                str(repository),
                "--output",
                str(baseline),
            )
            self.assertEqual(0, first.returncode, first.stderr)
            first_bytes = baseline.read_bytes()
            second = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "create",
                "--repo",
                str(repository),
                "--output",
                str(baseline),
            )
            self.assertEqual(2, second.returncode, second.stderr)
            self.assertEqual(first_bytes, baseline.read_bytes())

            modified.write_text("after", encoding="utf-8")
            deleted.unlink()
            (allowed / "added.txt").write_text("new", encoding="utf-8")
            (repository / "outside.txt").write_text("out of scope", encoding="utf-8")
            comparison = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "compare",
                "--repo",
                str(repository),
                "--baseline",
                str(baseline),
                "--write-scope",
                "allowed",
            )
            self.assertNotEqual("", comparison.stdout, comparison.stderr)
            report = json.loads(comparison.stdout)

            self.assertEqual(["allowed/added.txt", "outside.txt"], report["added"])
            self.assertEqual(["allowed/modified.txt"], report["modified"])
            self.assertEqual(["allowed/deleted.txt"], report["deleted"])
            self.assertEqual(["outside.txt"], report["out_of_scope"])

            before_failed_retry = baseline.read_bytes()
            failed = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "create",
                "--repo",
                str(repository),
                "--output",
                str(baseline),
                "--scope",
                "../escape",
            )
            self.assertNotEqual(0, failed.returncode)
            self.assertEqual(before_failed_retry, baseline.read_bytes())

    def test_snapshot_does_not_follow_escaping_symbolic_link(self) -> None:
        """External symlink contents never enter or influence the manifest."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            repository.mkdir()
            external = base / "outside-secret.txt"
            external.write_text("secret-one", encoding="utf-8")
            (repository / "escape").symlink_to(external)
            baseline = repository / ".codex/project-workflow/test/baseline.json"

            created = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "create",
                "--repo",
                str(repository),
                "--output",
                str(baseline),
            )
            self.assertEqual(0, created.returncode, created.stderr)
            manifest_text = baseline.read_text(encoding="utf-8")
            self.assertNotIn(str(external), manifest_text)
            self.assertNotIn(
                hashlib.sha256(b"secret-one").hexdigest(),
                manifest_text,
            )

            external.write_text("secret-two", encoding="utf-8")
            compared = self.run_script(
                FILESYSTEM_SNAPSHOT,
                "compare",
                "--repo",
                str(repository),
                "--baseline",
                str(baseline),
            )
            self.assertEqual(0, compared.returncode, compared.stderr)
            report = json.loads(compared.stdout)
            self.assertEqual([], report["added"])
            self.assertEqual([], report["modified"])
            self.assertEqual([], report["deleted"])

    def test_legacy_plan_without_vcs_fields_uses_auto_without_rewrite(self) -> None:
        """Historical plans retain bytes while receiving AUTO interpretation."""
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.init_git(repository)
            plan = repository / "legacy-plan.md"
            self.write_plan(
                plan,
                vcs_mode=None,
                resolved_vcs_mode=None,
            )
            before = plan.read_bytes()

            result, report = self.doctor(repository, "--plan", plan.name)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("AUTO", report["version_control"]["requested"])
            self.assertEqual("GIT", report["version_control"]["resolved"])
            self.assertEqual(before, plan.read_bytes())


if __name__ == "__main__":
    unittest.main()
