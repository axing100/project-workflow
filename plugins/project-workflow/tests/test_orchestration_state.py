"""Tests for the Project Workflow multi-agent orchestration helper."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATION_SCRIPT = PLUGIN_ROOT / "scripts" / "orchestration_state.py"
WORKFLOW_SCRIPT = PLUGIN_ROOT / "scripts" / "workflow_state.py"


class OrchestrationStateTest(unittest.TestCase):
    """Verify task DAG validation, scheduling, conflicts, and recovery."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.plan = root / "plan.md"
        self.state = root / "plan.orchestration.json"
        self.plan.write_text(
            "# Plan\n\nScheduler test.\n",
            encoding="utf-8",
        )
        self.run_workflow("init", str(self.plan), "--plan-id", "scheduler-test")
        self.run_workflow(
            "approve",
            str(self.plan),
            "--confirmation",
            "I approve scheduler-test revision 1.",
            "--at",
            "2026-08-20T00:00:00+00:00",
        )
        self.run_workflow("transition", str(self.plan), "IN_PROGRESS")
        self.write_state(self.default_state())

    def default_task(
        self,
        task_id: str,
        dependencies: list[str],
        scopes: list[str],
        eligible: bool = True,
    ) -> dict[str, object]:
        """Create a valid pending scheduler task."""
        return {
            "id": task_id,
            "status": "PENDING",
            "depends_on": dependencies,
            "write_scope": scopes,
            "agent_eligible": eligible,
            "owner": "",
            "started_at": "",
            "attempts": 0,
            "evidence": [],
            "block_reason": "",
            "parallel_group": "",
            "planned_owner": "",
            "branch_or_worktree": "",
            "assignment_kind": "",
        }

    def default_state(self) -> dict[str, object]:
        """Create a valid two-wave state document."""
        return {
            "schema": "project-workflow/orchestration/v1",
            "plan_id": "scheduler-test",
            "revision": 1,
            "execution_mode": "AUTO_MULTI_AGENT",
            "max_workers": 2,
            "max_attempts": 2,
            "topology": "SHARED_WORKSPACE",
            "tasks": [
                self.default_task("T01", [], ["module-a"]),
                self.default_task("T02", [], ["module-b"]),
                self.default_task("T03", ["T01", "T02"], ["integration"]),
            ],
            "events": [],
        }

    def write_state(self, state: dict[str, object]) -> None:
        """Write scheduler state for a test scenario."""
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def read_state(self) -> dict[str, object]:
        """Read the latest scheduler state."""
        return json.loads(self.state.read_text(encoding="utf-8"))

    def run_workflow(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the approval state helper."""
        result = subprocess.run(
            [sys.executable, str(WORKFLOW_SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def run_command(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the orchestration helper and assert its exit code."""
        result = subprocess.run(
            [sys.executable, str(ORCHESTRATION_SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def orchestration(self, command: str, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run a command that requires the canonical plan."""
        return self.run_command(
            command,
            str(self.state),
            *arguments,
            "--plan",
            str(self.plan),
            expected=expected,
        )

    def test_validate_and_ready_wave(self) -> None:
        """Return independent root tasks as the first safe wave."""
        self.orchestration("validate", "--require-approval")
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T01", "T02"], [item["id"] for item in json.loads(result.stdout)])

    def test_assignment_completion_unlocks_dependency(self) -> None:
        """Complete root tasks before returning their dependent task."""
        self.orchestration("assign", "T01", "--owner", "worker-a")
        self.orchestration("assign", "T02", "--owner", "worker-b")
        self.orchestration("complete", "T01", "--evidence", "tests passed")
        self.orchestration("complete", "T02", "--evidence", "review passed")
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T03"], [item["id"] for item in json.loads(result.stdout)])

    def test_overlapping_scope_is_not_ready_or_assignable(self) -> None:
        """Prevent concurrent assignment of nested write scopes."""
        state = self.default_state()
        state["tasks"] = [
            self.default_task("T01", [], ["module-a"]),
            self.default_task("T02", [], ["module-a/service"]),
        ]
        self.write_state(state)
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T01"], [item["id"] for item in json.loads(result.stdout)])
        self.orchestration("assign", "T01", "--owner", "worker-a")
        failure = self.orchestration(
            "assign", "T02", "--owner", "worker-b", expected=2
        )
        self.assertIn("write scope conflicts", failure.stderr)

    def test_release_allows_retry_and_increments_attempts(self) -> None:
        """Release a failed assignment and preserve bounded attempt history."""
        self.orchestration("assign", "T01", "--owner", "worker-a")
        self.orchestration("release", "T01", "--reason", "worker stopped")
        self.orchestration("assign", "T01", "--owner", "worker-b")
        task = self.read_state()["tasks"][0]
        self.assertEqual("ASSIGNED", task["status"])
        self.assertEqual(2, task["attempts"])
        self.assertEqual("worker-b", task["owner"])

    def test_block_and_release(self) -> None:
        """Persist a blocker and release it after resolution."""
        self.orchestration("block", "T01", "--reason", "missing contract")
        self.assertEqual("BLOCKED", self.read_state()["tasks"][0]["status"])
        self.orchestration("release", "T01", "--reason", "contract supplied")
        self.assertEqual("PENDING", self.read_state()["tasks"][0]["status"])

    def test_unknown_dependency_and_cycle_are_rejected(self) -> None:
        """Reject invalid dependency graphs."""
        state = self.default_state()
        state["tasks"][0]["depends_on"] = ["T99"]
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("unknown dependencies", failure.stderr)

        state = self.default_state()
        state["tasks"][0]["depends_on"] = ["T03"]
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("dependency cycle", failure.stderr)

    def test_revision_mismatch_is_rejected(self) -> None:
        """Require scheduler and approved plan revisions to match."""
        state = self.default_state()
        state["revision"] = 2
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("revision does not match", failure.stderr)

    def test_single_agent_mode_rejects_assignment(self) -> None:
        """Do not delegate a plan that requires single-agent execution."""
        state = self.default_state()
        state["execution_mode"] = "SINGLE_AGENT"
        self.write_state(state)
        failure = self.orchestration(
            "assign", "T01", "--owner", "worker-a", expected=2
        )
        self.assertIn("does not permit worker assignment", failure.stderr)

    def test_single_agent_mode_allows_coordinator_assignment(self) -> None:
        """Track serial coordinator work without consuming worker permission."""
        state = self.default_state()
        state["execution_mode"] = "SINGLE_AGENT"
        state["tasks"][0]["agent_eligible"] = False
        self.write_state(state)
        self.orchestration(
            "assign", "T01", "--owner", "coordinator", "--coordinator"
        )
        task = self.read_state()["tasks"][0]
        self.assertEqual("COORDINATOR", task["assignment_kind"])

    def test_manual_mode_requires_matching_planned_owner(self) -> None:
        """Restrict manual delegation to the approved worker assignment."""
        state = self.default_state()
        state["execution_mode"] = "MANUAL_MULTI_AGENT"
        for task in state["tasks"]:
            task["planned_owner"] = f"worker-{task['id'].lower()}"
        self.write_state(state)
        failure = self.orchestration(
            "assign", "T01", "--owner", "another-worker", expected=2
        )
        self.assertIn("must use planned_owner", failure.stderr)
        self.orchestration("assign", "T01", "--owner", "worker-t01")

    def test_max_attempts_stops_retry_loop(self) -> None:
        """Reject assignment after the approved retry limit is reached."""
        state = self.default_state()
        state["tasks"][0]["attempts"] = 2
        self.write_state(state)
        failure = self.orchestration(
            "assign", "T01", "--owner", "worker-a", expected=2
        )
        self.assertIn("reached max_attempts", failure.stderr)

    def test_completed_task_requires_evidence(self) -> None:
        """Reject completed records without coordinator evidence."""
        state = self.default_state()
        state["tasks"][0]["status"] = "COMPLETED"
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("requires evidence", failure.stderr)


if __name__ == "__main__":
    unittest.main()
