"""Tests for the Project Workflow state helper."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"


class WorkflowStateTest(unittest.TestCase):
    """Verify approval gates, transitions, and Markdown preservation."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plan = Path(self.temporary_directory.name) / "plan.md"
        self.plan.write_text("# Implementation Plan\n\nKeep this body.\n", encoding="utf-8")

    def run_command(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the state helper and assert its exit code."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def initialize(self) -> None:
        """Initialize the test plan at the confirmation boundary."""
        self.run_command("init", str(self.plan), "--plan-id", "test-plan")

    def approve(self) -> None:
        """Record deterministic approval for the test plan."""
        self.run_command(
            "approve",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            "--at",
            "2026-08-20T00:00:00+00:00",
        )

    def inspect(self) -> dict[str, object]:
        """Return inspected workflow metadata."""
        result = self.run_command("inspect", str(self.plan))
        return json.loads(result.stdout)

    def test_init_preserves_markdown_body(self) -> None:
        self.initialize()
        metadata = self.inspect()
        self.assertEqual("AWAITING_CONFIRMATION", metadata["phase"])
        self.assertEqual(1, metadata["revision"])
        self.assertIn("# Implementation Plan\n\nKeep this body.\n", self.plan.read_text(encoding="utf-8"))

    def test_unapproved_plan_cannot_execute(self) -> None:
        self.initialize()
        result = self.run_command("check-execute", str(self.plan), expected=2)
        self.assertIn("execution requires APPROVED", result.stderr)

    def test_approved_current_revision_can_execute(self) -> None:
        self.initialize()
        self.approve()
        result = self.run_command("check-execute", str(self.plan))
        self.assertIn("execution allowed", result.stdout)

    def test_revision_mismatch_cannot_execute(self) -> None:
        self.initialize()
        self.approve()
        content = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(content.replace("revision: 1", "revision: 2", 1), encoding="utf-8")
        result = self.run_command("check-execute", str(self.plan), expected=2)
        self.assertIn("does not match revision 2", result.stderr)

    def test_illegal_transition_is_rejected(self) -> None:
        self.initialize()
        result = self.run_command("transition", str(self.plan), "COMPLETED", expected=2)
        self.assertIn("illegal transition", result.stderr)

    def test_material_change_requires_revision_increment(self) -> None:
        self.initialize()
        self.approve()
        result = self.run_command(
            "transition", str(self.plan), "AWAITING_CONFIRMATION", expected=2
        )
        self.assertIn("requires --increment-revision", result.stderr)

        self.run_command(
            "transition",
            str(self.plan),
            "AWAITING_CONFIRMATION",
            "--increment-revision",
        )
        metadata = self.inspect()
        self.assertEqual(2, metadata["revision"])
        self.assertEqual("AWAITING_CONFIRMATION", metadata["phase"])
        self.assertEqual("", metadata["approved_revision"])
        self.assertEqual("", metadata["confirmation_record"])

    def test_execution_progress_and_completion(self) -> None:
        self.initialize()
        self.approve()
        self.run_command("transition", str(self.plan), "IN_PROGRESS")
        self.run_command("check-execute", str(self.plan))
        self.run_command("transition", str(self.plan), "COMPLETED")
        self.assertEqual("COMPLETED", self.inspect()["phase"])


if __name__ == "__main__":
    unittest.main()
