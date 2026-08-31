"""Tests for structured task progress and localized plan rendering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_state.py"
WORKFLOW_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"


class TaskStateTest(unittest.TestCase):
    """Verify migration, transitions, localization, and rendering."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name)
        subprocess.run(
            ["git", "init", "-q", str(self.repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.plan = self.repo / "docs/plan/001-plan.md"
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text(
            """---
workflow: "project-workflow/v1"
policy_contract: "v0.5"
plan_id: "test-plan"
revision: 1
phase: "IN_PROGRESS"
approved_revision: 1
approved_at: "2026-08-31T00:00:00+00:00"
confirmation_record: "approved"
execution_mode: "SINGLE_AGENT"
vcs_mode: "GIT"
resolved_vcs_mode: "GIT"
---

# Example plan

Free text stays unchanged.

## T01 Build

- 状态：[~]
- Depends-On：无
- 验收标准：
  - [ ] observable check

## T02 Verify

- 状态：[ ]
- Depends-On：T01
""",
            encoding="utf-8",
        )

    def run_command(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the helper and assert a stable exit status."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments, "--repo", str(self.repo)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def migrate(self, language: str = "zh-CN") -> dict[str, object]:
        """Migrate the fixture and return its state."""
        result = self.run_command(
            "migrate", str(self.plan), "--display-language", language
        )
        return json.loads(result.stdout)

    def test_migrate_splits_legacy_state_and_removes_adjacent_status(self) -> None:
        """Conservatively split legacy progress into implementation and verification."""
        state = self.migrate()

        self.assertEqual("IN_PROGRESS", state["tasks"][0]["implementation_status"])
        self.assertEqual("NOT_STARTED", state["tasks"][0]["verification_status"])
        content = self.plan.read_text(encoding="utf-8")
        self.assertNotIn("- 状态：[~]", content)
        self.assertIn("- 实现状态：🔵 进行中", content)
        self.assertIn("- 验收状态：⚪ 未开始", content)
        self.assertIn("  - [ ] observable check", content)
        self.assertTrue((self.repo / ".codex/project-workflow/test-plan/state.json").is_file())
        self.assertFalse(any(self.plan.parent.glob(".*.lock")))

    def test_render_is_byte_for_byte_idempotent(self) -> None:
        """Replace controlled blocks without accumulating Markdown changes."""
        self.migrate()
        first = self.plan.read_bytes()
        self.run_command("render", str(self.plan))
        self.assertEqual(first, self.plan.read_bytes())
        self.run_command("migrate", str(self.plan), "--display-language", "en-US")
        self.assertEqual(first, self.plan.read_bytes())

    def test_unsupported_language_falls_back_to_english(self) -> None:
        """Use English for every language other than the two supported locales."""
        state = self.migrate("fr-FR")

        self.assertEqual("en-US", state["display_language"])
        content = self.plan.read_text(encoding="utf-8")
        self.assertIn("- Implementation：🔵 In progress", content)
        self.assertIn("- Verification：⚪ Not started", content)

    def test_completion_and_partial_verification_are_independent(self) -> None:
        """Show completed implementation while verification remains partial."""
        state = self.migrate()
        version = state["state_version"]
        self.run_command(
            "complete-implementation",
            str(self.plan),
            "T01",
            "--evidence",
            "unit tests passed",
            "--expected-version",
            str(version),
        )
        self.run_command("start-verification", str(self.plan), "T01")
        result = self.run_command(
            "partial-verification",
            str(self.plan),
            "T01",
            "--evidence",
            "integration environment unavailable",
        )
        state = json.loads(result.stdout)

        self.assertEqual("COMPLETED", state["tasks"][0]["implementation_status"])
        self.assertEqual("PARTIAL", state["tasks"][0]["verification_status"])
        content = self.plan.read_text(encoding="utf-8")
        self.assertIn("- 实现状态：✅ 已完成", content)
        self.assertIn("- 验收状态：🟡 部分通过", content)

    def test_dependency_single_agent_and_evidence_gates(self) -> None:
        """Reject dependency bypass, concurrent work, and evidence-free completion."""
        self.migrate()

        blocked = self.run_command(
            "start-implementation", str(self.plan), "T02", expected=2
        )
        self.assertIn("dependencies", blocked.stderr)
        missing = self.run_command(
            "complete-implementation", str(self.plan), "T01", expected=2
        )
        self.assertIn("evidence", missing.stderr)

    def test_state_version_compare_and_swap_rejects_stale_writer(self) -> None:
        """Reject a stale mutation before changing state or Markdown."""
        state = self.migrate()
        content = self.plan.read_bytes()

        result = self.run_command(
            "block-implementation",
            str(self.plan),
            "T01",
            "--reason",
            "waiting",
            "--expected-version",
            str(state["state_version"] + 1),
            expected=2,
        )

        self.assertIn("version conflict", result.stderr)
        self.assertEqual(content, self.plan.read_bytes())

    def test_unknown_schema_fails_closed_without_traceback(self) -> None:
        """Reject future state schemas through a stable public error."""
        self.migrate()
        path = self.repo / ".codex/project-workflow/test-plan/state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["schema"] = "project-workflow/task-state/v9"
        path.write_text(json.dumps(state), encoding="utf-8")

        result = self.run_command("inspect", str(self.plan), expected=2)

        self.assertIn("unsupported task state schema", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_lifecycle_completion_requires_and_binds_final_task_state(self) -> None:
        """Block incomplete work and bind the accepted state version at completion."""
        self.migrate()
        incomplete = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_SCRIPT),
                "complete",
                str(self.plan),
                "--repo",
                str(self.repo),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, incomplete.returncode)
        self.assertIn("implementation is incomplete", incomplete.stderr)

        commands = (
            ("complete-implementation", "T01", "--evidence", "built"),
            ("start-verification", "T01"),
            ("pass-verification", "T01", "--evidence", "checked"),
            ("start-implementation", "T02"),
            ("complete-implementation", "T02", "--evidence", "built"),
            ("skip-verification", "T02", "--evidence", "documentation-only"),
        )
        for command in commands:
            self.run_command(command[0], str(self.plan), command[1], *command[2:])
        completed = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_SCRIPT),
                "complete",
                str(self.plan),
                "--repo",
                str(self.repo),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        content = self.plan.read_text(encoding="utf-8")
        self.assertIn('phase: "COMPLETED"', content)
        self.assertRegex(content, r"final_task_state_version: [1-9][0-9]*")


if __name__ == "__main__":
    unittest.main()
