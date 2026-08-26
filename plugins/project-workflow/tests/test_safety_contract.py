"""Independent black-box safety contract tests for Project Workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "project-workflow" / "scripts"
DOCTOR = SCRIPTS / "project_workflow_doctor.py"
WORKFLOW = SCRIPTS / "workflow_state.py"
SNAPSHOT = SCRIPTS / "filesystem_snapshot.py"


def run_cli(script: Path, *args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run one public helper exactly as an external caller would."""
    return subprocess.run(
        [sys.executable, str(script), *(str(arg) for arg in args)],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def plan_text(
    *,
    phase: str = "BLOCKED",
    profile: str = "FULL",
    vcs_mode: str = "NONE",
    resolved: str = "NONE",
    approved_revision: str = "1",
    confirmation: str = "approved",
    rollback_fields: str = "",
    topology: str = "SHARED_WORKSPACE",
    rollback_required: str = "false",
) -> str:
    """Return a minimal public-protocol plan document."""
    return f"""---
workflow: "project-workflow/v1"
plan_id: "black-box-plan"
revision: 1
phase: "{phase}"
workflow_profile: "{profile}"
approved_revision: {approved_revision}
approved_at: "2026-08-25T00:00:00+00:00"
confirmation_record: "{confirmation}"
conversation_title: "Black-box contract"
progress_heartbeat_minutes: 5
vcs_mode: "{vcs_mode}"
resolved_vcs_mode: "{resolved}"
rollback_required: "{rollback_required}"
execution_mode: "SINGLE_AGENT"
max_workers: 1
agent_topology: "{topology}"
{rollback_fields}---

# Black-box plan
"""


class DoctorSafetyContractTests(unittest.TestCase):
    """Verify Doctor trust and path boundaries through its public CLI."""

    def test_doctor_does_not_execute_repository_supplied_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            fake_scripts = repo / "plugins" / "project-workflow" / "scripts"
            fake_scripts.mkdir(parents=True)
            marker = repo / "untrusted-helper-ran"
            payload = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
            for name in ("workflow_state.py", "orchestration_state.py", "filesystem_snapshot.py"):
                (fake_scripts / name).write_text(payload, encoding="utf-8")

            result = run_cli(DOCTOR, "--repo", repo, "--json")

            self.assertFalse(marker.exists(), result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_doctor_blocks_symlinked_state_root_without_writing_outside(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            repo = Path(directory)
            outside = Path(outside_dir)
            (repo / ".codex").mkdir()
            (repo / ".codex" / "project-workflow").symlink_to(outside, target_is_directory=True)

            result = run_cli(DOCTOR, "--repo", repo, "--json")

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("BLOCKED", payload["status"])
            self.assertFalse(any(outside.iterdir()))

    def test_doctor_rejects_corrupt_orchestration_state_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(plan_text(profile="STANDARD"), encoding="utf-8")
            state = repo / "state.json"
            state.write_text('{"workflow": "project-workflow/orchestration/v1", "tasks":', encoding="utf-8")

            result = run_cli(
                DOCTOR,
                "--repo",
                repo,
                "--plan",
                "plan.md",
                "--orchestration",
                "state.json",
                "--json",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("BLOCKED", payload["status"])


class LifecycleSafetyContractTests(unittest.TestCase):
    """Verify rollback and resume gates are atomic."""

    def test_full_none_resume_requires_verified_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(plan_text(), encoding="utf-8")
            before = plan.read_bytes()

            result = run_cli(WORKFLOW, "resume", "plan.md", "--repo", repo)

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertEqual(before, plan.read_bytes())
            self.assertNotIn("Traceback", result.stderr)

    def test_full_none_resume_accepts_complete_verified_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text("# Black-box plan\n", encoding="utf-8")
            initialized = run_cli(
                WORKFLOW,
                "init",
                "plan.md",
                "--repo",
                repo,
                "--plan-id",
                "black-box-plan",
                "--vcs-mode",
                "NONE",
                cwd=repo,
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            text = plan.read_text(encoding="utf-8").replace(
                "---\n\n# Black-box plan",
                'workflow_profile: "FULL"\n'
                'rollback_required: "false"\n'
                'rollback_strategy: "restore archive"\n'
                'rollback_evidence: "archive restored in rehearsal"\n'
                'rollback_verification: "VERIFIED"\n'
                "filesystem_snapshot_scopes: []\n"
                "filesystem_snapshot_excludes: []\n"
                'filesystem_write_scopes: ["plan.md"]\n---\n\n# Black-box plan',
                1,
            )
            plan.write_text(text, encoding="utf-8")
            started = run_cli(
                WORKFLOW,
                "start-execution",
                "plan.md",
                "--repo",
                repo,
                "--confirmation",
                "approved",
                cwd=repo,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            blocked = run_cli(
                WORKFLOW,
                "transition",
                "plan.md",
                "BLOCKED",
                "--repo",
                repo,
                cwd=repo,
            )
            self.assertEqual(0, blocked.returncode, blocked.stderr)

            result = run_cli(WORKFLOW, "resume", "plan.md", "--repo", repo)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            inspected = run_cli(WORKFLOW, "inspect", "plan.md", cwd=repo)
            self.assertEqual("IN_PROGRESS", json.loads(inspected.stdout)["phase"])

    def test_standard_none_rollback_required_uses_same_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(
                plan_text(profile="STANDARD", rollback_required="true"),
                encoding="utf-8",
            )
            before = plan.read_bytes()

            result = run_cli(WORKFLOW, "resume", "plan.md", "--repo", repo)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, plan.read_bytes())

    def test_resume_vcs_resolution_drift_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(
                plan_text(profile="STANDARD", vcs_mode="AUTO", resolved="GIT"),
                encoding="utf-8",
            )
            before = plan.read_bytes()

            result = run_cli(WORKFLOW, "resume", "plan.md", "--repo", repo)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, plan.read_bytes())
            self.assertNotIn("Traceback", result.stderr)

    def test_low_level_transition_cannot_bypass_blocked_resume_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(plan_text(), encoding="utf-8")
            before = plan.read_bytes()

            result = run_cli(WORKFLOW, "transition", plan, "IN_PROGRESS")

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, plan.read_bytes())

    def test_start_execution_failure_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(
                plan_text(
                    phase="AWAITING_CONFIRMATION",
                    approved_revision="",
                    confirmation="",
                ),
                encoding="utf-8",
            )
            before = plan.read_bytes()

            result = run_cli(
                WORKFLOW,
                "start-execution",
                "plan.md",
                "--confirmation",
                "approve this plan",
                "--repo",
                repo,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, plan.read_bytes())


class SnapshotSafetyContractTests(unittest.TestCase):
    """Verify NONE-mode evidence path, output, scope, and compatibility contracts."""

    def test_create_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            repo = Path(directory)
            outside = Path(outside_dir)
            (repo / ".codex").mkdir()
            (repo / ".codex" / "project-workflow").symlink_to(outside, target_is_directory=True)
            (repo / "tracked.txt").write_text("safe", encoding="utf-8")

            result = run_cli(
                SNAPSHOT,
                "create",
                "--repo",
                repo,
                "--output",
                ".codex/project-workflow/p/baseline.json",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((outside / "p" / "baseline.json").exists())
            self.assertNotIn("Traceback", result.stderr)

    def test_relative_paths_summary_excludes_and_json_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "src").mkdir()
            (repo / "src" / "a.txt").write_text("a", encoding="utf-8")
            (repo / "cache").mkdir()
            (repo / "cache" / "ignored.bin").write_bytes(b"x" * 128)

            summary = run_cli(
                SNAPSHOT,
                "create",
                "--repo",
                repo,
                "--output",
                ".codex/project-workflow/p/base.json",
                "--exclude",
                "cache",
            )
            self.assertEqual(0, summary.returncode, summary.stdout + summary.stderr)
            summary_payload = json.loads(summary.stdout)
            self.assertNotIn("files", summary_payload)
            self.assertEqual(1, summary_payload["file_count"])
            self.assertEqual(["cache"], summary_payload["excludes"])
            self.assertEqual(".codex/project-workflow/p/base.json", summary_payload["output"])
            baseline = repo / ".codex" / "project-workflow" / "p" / "base.json"
            self.assertTrue(baseline.is_file())

            detailed = run_cli(
                SNAPSHOT,
                "create",
                "--repo",
                repo,
                "--output",
                ".codex/project-workflow/p/details.json",
                "--exclude",
                "cache",
                "--json-details",
            )
            self.assertEqual(0, detailed.returncode, detailed.stderr)
            details = json.loads(detailed.stdout)
            self.assertIn("files", details)
            paths = [item["path"] for item in details["files"]]
            self.assertIn("src/a.txt", paths)
            self.assertNotIn("cache/ignored.bin", paths)

    def test_compare_detects_mode_and_fails_out_of_scope_with_stable_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            target = repo / "tool.sh"
            target.write_text("#!/bin/sh\n", encoding="utf-8")
            baseline = ".codex/project-workflow/p/base.json"
            created = run_cli(SNAPSHOT, "create", "--repo", repo, "--output", baseline)
            self.assertEqual(0, created.returncode, created.stderr)
            target.chmod(target.stat().st_mode | stat.S_IXUSR)

            result = run_cli(
                SNAPSHOT,
                "compare",
                "--repo",
                repo,
                "--baseline",
                baseline,
                "--write-scope",
                "allowed",
            )

            self.assertEqual(3, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("tool.sh", payload["modified"])
            self.assertIn("tool.sh", payload["out_of_scope"])

            report_only = run_cli(
                SNAPSHOT,
                "compare",
                "--repo",
                repo,
                "--baseline",
                baseline,
                "--write-scope",
                "allowed",
                "--report-only",
            )
            self.assertEqual(0, report_only.returncode, report_only.stderr)


if __name__ == "__main__":
    unittest.main()
