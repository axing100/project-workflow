"""Independent black-box tests for the Project Workflow v0.4 contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_STATE = PLUGIN_ROOT / "scripts/workflow_state.py"
ORCHESTRATION_STATE = PLUGIN_ROOT / "scripts/orchestration_state.py"
DOCTOR = PLUGIN_ROOT / "scripts/project_workflow_doctor.py"


class WorkflowContractTest(unittest.TestCase):
    """Exercise public CLIs without importing their implementation modules."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()
        self.plan = self.repo / "docs/plan/contract.md"
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text("# Contract plan\n", encoding="utf-8")

    def run_cli(
        self,
        script: Path,
        *arguments: str,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        """Run a public helper and assert its documented exit status."""
        result = subprocess.run(
            [sys.executable, str(script), *map(str, arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def initialize_plan(self, profile: str | None = "FULL") -> None:
        """Create a plan through the public helper and add public v0.4 metadata."""
        plan_id = f"contract-{self.plan.stem}"
        self.run_cli(WORKFLOW_STATE, "init", self.plan, "--plan-id", plan_id)
        text = self.plan.read_text(encoding="utf-8")
        profile_line = f"workflow_profile: {profile}\n" if profile else ""
        metadata = profile_line + (
            "execution_mode: AUTO_MULTI_AGENT\n"
            "max_workers: 2\n"
            "agent_topology: SHARED_WORKSPACE\n"
            "parallelism_policy: BENEFIT_GATED\n"
        )
        text = text.replace("\n---\n", f"\n{metadata}---\n", 1)
        self.plan.write_text(text, encoding="utf-8")

    def test_experience_contract_is_available_to_new_and_legacy_plans(self) -> None:
        """Provide deterministic title and heartbeat values across plan generations."""
        self.initialize_plan("STANDARD")
        current = json.loads(
            self.run_cli(WORKFLOW_STATE, "experience", self.plan).stdout
        )
        self.assertEqual("Contract plan", current["conversation_title"])
        self.assertEqual(5, current["progress_heartbeat_minutes"])

        text = self.plan.read_text(encoding="utf-8")
        text = "\n".join(
            line
            for line in text.splitlines()
            if not line.startswith("conversation_title:")
            and not line.startswith("progress_heartbeat_minutes:")
        ) + "\n"
        self.plan.write_text(text, encoding="utf-8")
        legacy = json.loads(
            self.run_cli(WORKFLOW_STATE, "experience", self.plan).stdout
        )
        self.assertEqual("Contract plan", legacy["conversation_title"])
        self.assertEqual(5, legacy["progress_heartbeat_minutes"])

    def start_plan(self, profile: str | None = "FULL") -> None:
        """Initialize and atomically enter execution."""
        self.initialize_plan(profile)
        self.run_cli(
            WORKFLOW_STATE,
            "start-execution",
            self.plan,
            "--confirmation",
            "I approve contract-plan revision 1.",
            "--at",
            "2026-08-23T01:02:03+00:00",
        )

    @staticmethod
    def task(
        task_id: str,
        *,
        estimated: object | None = None,
        coordination: object | None = None,
        role: str | None = None,
        independent: object | None = None,
    ) -> dict[str, object]:
        """Build one task using only fields documented by the public protocol."""
        task: dict[str, object] = {
            "id": task_id,
            "display_name": f"Task {task_id}",
            "depends_on": [],
            "write_scope": [f"scope/{task_id.lower()}"],
            "agent_eligible": True,
            "critical_path": True,
        }
        if estimated is not None:
            task["estimated_minutes"] = estimated
        if coordination is not None:
            task["coordination_minutes"] = coordination
        if role is not None:
            task["role"] = role
        if independent is not None:
            task["independent_verification"] = independent
        return task

    def initialize_state(self, *tasks: dict[str, object]) -> Path:
        """Create scheduler state through its public init command."""
        plan_id = json.loads(
            self.run_cli(WORKFLOW_STATE, "inspect", self.plan).stdout
        )["plan_id"]
        state = self.repo / f".codex/project-workflow/{plan_id}/orchestration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        arguments: list[str | Path] = ["init", state, "--plan", self.plan]
        for task in tasks:
            arguments.extend(("--task", json.dumps(task)))
        self.run_cli(ORCHESTRATION_STATE, *arguments)
        return state

    def ready(self, state: Path, *, expected: int = 0) -> list[dict[str, object]]:
        """Return the public safe Worker wave."""
        result = self.run_cli(
            ORCHESTRATION_STATE,
            "ready",
            state,
            "--plan",
            self.plan,
            "--agent-only",
            expected=expected,
        )
        return json.loads(result.stdout) if expected == 0 else []

    def test_start_execution_is_atomic_and_preserves_confirmation(self) -> None:
        """A retry from IN_PROGRESS must fail without rewriting any approval data."""
        self.start_plan("STANDARD")
        first_bytes = self.plan.read_bytes()
        inspected = json.loads(
            self.run_cli(WORKFLOW_STATE, "inspect", self.plan).stdout
        )
        self.assertEqual("IN_PROGRESS", inspected["phase"])
        self.assertEqual(1, inspected["approved_revision"])
        self.assertEqual(
            "I approve contract-plan revision 1.", inspected["confirmation_record"]
        )
        self.assertEqual("2026-08-23T01:02:03+00:00", inspected["approved_at"])

        self.run_cli(
            WORKFLOW_STATE,
            "start-execution",
            self.plan,
            "--confirmation",
            "replacement must not persist",
            expected=2,
        )
        self.assertEqual(first_bytes, self.plan.read_bytes())

    def test_start_execution_invalid_time_is_atomic_and_has_stable_error(self) -> None:
        """Reject malformed time before any frontmatter field is partially updated."""
        self.initialize_plan("STANDARD")
        before = self.plan.read_bytes()
        failure = self.run_cli(
            WORKFLOW_STATE,
            "start-execution",
            self.plan,
            "--confirmation",
            "approved",
            "--at",
            "not-a-time",
            expected=2,
        )
        self.assertEqual(before, self.plan.read_bytes())
        self.assertNotIn("Traceback", failure.stderr)

    def test_complete_is_guarded_and_not_idempotent(self) -> None:
        """Only IN_PROGRESS may complete; retries fail without rewriting the plan."""
        self.initialize_plan("LIGHT")
        before = self.plan.read_bytes()
        self.run_cli(WORKFLOW_STATE, "complete", self.plan, expected=2)
        self.assertEqual(before, self.plan.read_bytes())

        self.run_cli(
            WORKFLOW_STATE,
            "start-execution",
            self.plan,
            "--confirmation",
            "approved",
        )
        self.run_cli(WORKFLOW_STATE, "complete", self.plan)
        completed = self.plan.read_bytes()
        self.run_cli(WORKFLOW_STATE, "complete", self.plan, expected=2)
        self.assertEqual(completed, self.plan.read_bytes())

    def test_legacy_plan_without_profile_remains_executable(self) -> None:
        """Treat a v0.3 plan with no new fields as compatible FULL behavior."""
        self.start_plan(profile=None)
        inspected = json.loads(
            self.run_cli(WORKFLOW_STATE, "inspect", self.plan).stdout
        )
        self.assertEqual("IN_PROGRESS", inspected["phase"])
        self.assertNotIn("workflow_profile", inspected)

    def test_benefit_gate_accepts_exactly_twenty_percent(self) -> None:
        """Accept the inclusive default threshold and reject values just below it."""
        self.start_plan("STANDARD")
        state = self.initialize_state(
            self.task("T01", estimated=10, coordination=3),
            self.task("T02", estimated=10, coordination=3),
        )
        self.assertEqual(["T01", "T02"], [item["id"] for item in self.ready(state)])

        state_payload = json.loads(state.read_text(encoding="utf-8"))
        state_payload["tasks"][0]["coordination_minutes"] = 3.0000001
        state.write_text(json.dumps(state_payload), encoding="utf-8")
        self.assertEqual([], self.ready(state))

    def test_benefit_gate_rejects_invalid_numeric_extremes(self) -> None:
        """Reject bool, non-finite, negative, zero-duration, and huge policy inputs."""
        invalid_values: tuple[object, ...] = (
            True,
            -1,
            float("inf"),
            float("nan"),
            10**100,
        )
        for index, invalid in enumerate(invalid_values):
            with self.subTest(value=invalid):
                self.plan = self.repo / f"docs/plan/invalid-{index}.md"
                self.plan.write_text("# Invalid contract plan\n", encoding="utf-8")
                self.start_plan("STANDARD")
                state = self.initialize_state(
                    self.task("T01", estimated=10, coordination=1),
                    self.task("T02", estimated=10, coordination=1),
                )
                payload = json.loads(state.read_text(encoding="utf-8"))
                payload["tasks"][0]["estimated_minutes"] = invalid
                state.write_text(json.dumps(payload), encoding="utf-8")
                failure = self.run_cli(
                    ORCHESTRATION_STATE,
                    "validate",
                    state,
                    "--plan",
                    self.plan,
                    expected=2,
                )
                self.assertNotIn("Traceback", failure.stderr)

    def test_zero_estimate_is_handled_without_false_parallel_benefit(self) -> None:
        """Treat zero as a boundary value without crashing or inventing savings."""
        self.start_plan("STANDARD")
        state = self.initialize_state(
            self.task("T01", estimated=0, coordination=1),
            self.task("T02", estimated=10, coordination=1),
        )
        self.run_cli(ORCHESTRATION_STATE, "validate", state, "--plan", self.plan)
        self.assertEqual([], self.ready(state))

    def test_single_contract_verifier_is_the_only_one_task_exception(self) -> None:
        """Permit isolated verification alone, but not an ordinary or mislabeled task."""
        cases = (
            (self.task("T01", estimated=10, coordination=1), []),
            (
                self.task(
                    "T01",
                    estimated=10,
                    coordination=1,
                    role="CONTRACT_VERIFIER",
                    independent=False,
                ),
                [],
            ),
            (
                self.task(
                    "T01",
                    estimated=10,
                    coordination=1,
                    role="CONTRACT_VERIFIER",
                    independent=True,
                ),
                ["T01"],
            ),
        )
        for index, (task, expected_ids) in enumerate(cases):
            with self.subTest(index=index):
                self.plan = self.repo / f"docs/plan/verifier-{index}.md"
                self.plan.write_text("# Verifier plan\n", encoding="utf-8")
                self.start_plan("STANDARD")
                state = self.initialize_state(task)
                self.assertEqual(expected_ids, [item["id"] for item in self.ready(state)])

    def test_contract_verifier_must_have_isolated_write_scope(self) -> None:
        """Reject FULL verification that can overwrite the implementation under test."""
        self.start_plan("FULL")
        implementation = self.task("T01", estimated=10, coordination=1)
        verifier = self.task(
            "T02",
            estimated=10,
            coordination=1,
            role="CONTRACT_VERIFIER",
            independent=True,
        )
        verifier["write_scope"] = implementation["write_scope"]
        plan_id = json.loads(
            self.run_cli(WORKFLOW_STATE, "inspect", self.plan).stdout
        )["plan_id"]
        state = self.repo / f".codex/project-workflow/{plan_id}/orchestration.json"
        state.parent.mkdir(parents=True)
        failure = self.run_cli(
            ORCHESTRATION_STATE,
            "init",
            state,
            "--plan",
            self.plan,
            "--task",
            json.dumps(implementation),
            "--task",
            json.dumps(verifier),
            expected=2,
        )
        self.assertIn("contract verifier", failure.stderr.lower())
        self.assertFalse(state.exists())

    def test_legacy_orchestration_without_benefit_fields_still_runs(self) -> None:
        """Keep v0.3 scheduler state readable when all v0.4 fields are absent."""
        self.start_plan("STANDARD")
        state = self.initialize_state(self.task("T01"), self.task("T02"))
        plan_text = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            "\n".join(
                line
                for line in plan_text.splitlines()
                if not line.startswith("workflow_profile:")
            )
            + "\n",
            encoding="utf-8",
        )
        payload = json.loads(state.read_text(encoding="utf-8"))
        payload.pop("parallelism_policy", None)
        payload.pop("minimum_parallel_savings_percent", None)
        payload.pop("policy_contract", None)
        for task in payload["tasks"]:
            for field in (
                "estimated_minutes",
                "coordination_minutes",
                "critical_path",
                "role",
                "independent_verification",
            ):
                task.pop(field, None)
        state.write_text(json.dumps(payload), encoding="utf-8")
        self.run_cli(ORCHESTRATION_STATE, "validate", state, "--plan", self.plan)
        self.assertEqual(["T01", "T02"], [item["id"] for item in self.ready(state)])

    def test_legacy_completed_worker_without_runtime_identity_is_readable(self) -> None:
        """Preserve v0.3 completion evidence without fabricating a native identity."""
        self.start_plan("STANDARD")
        state = self.initialize_state(self.task("T01"), self.task("T02"))
        plan_text = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            "\n".join(
                line
                for line in plan_text.splitlines()
                if not line.startswith("workflow_profile:")
            )
            + "\n",
            encoding="utf-8",
        )
        payload = json.loads(state.read_text(encoding="utf-8"))
        legacy = payload["tasks"][0]
        legacy.update(
            {
                "status": "COMPLETED",
                "owner": "legacy-worker",
                "assignment_kind": "WORKER",
                "started_at": "2026-08-20T00:00:00+00:00",
                "evidence": ["historical evidence"],
            }
        )
        for field in (
            "runtime_agent_id",
            "runtime_task_name",
            "spawn_status",
            "spawned_at",
            "finished_at",
            "runtime_verification",
        ):
            legacy.pop(field, None)
        payload.pop("parallelism_policy", None)
        payload.pop("minimum_parallel_savings_percent", None)
        payload.pop("policy_contract", None)
        state.write_text(json.dumps(payload), encoding="utf-8")
        self.run_cli(ORCHESTRATION_STATE, "validate", state, "--plan", self.plan)
        inspected = json.loads(
            self.run_cli(ORCHESTRATION_STATE, "inspect", state).stdout
        )
        self.assertEqual("UNAVAILABLE", inspected["tasks"][0]["runtime_verification"])

    def test_new_full_state_requires_independent_contract_verifier(self) -> None:
        """Reject a new FULL scheduler contract that omits its isolated verifier."""
        self.start_plan("FULL")
        plan_id = json.loads(
            self.run_cli(WORKFLOW_STATE, "inspect", self.plan).stdout
        )["plan_id"]
        state = self.repo / f".codex/project-workflow/{plan_id}/orchestration.json"
        state.parent.mkdir(parents=True)
        tasks = (
            self.task("T01", estimated=10, coordination=1),
            self.task("T02", estimated=10, coordination=1),
        )
        arguments: list[str | Path] = ["init", state, "--plan", self.plan]
        for task in tasks:
            arguments.extend(("--task", json.dumps(task)))
        failure = self.run_cli(
            ORCHESTRATION_STATE,
            *arguments,
            expected=2,
        )
        self.assertIn("contract verifier", failure.stderr.lower())
        self.assertFalse(state.exists())

    def test_doctor_has_stable_output_and_quiet_recovery(self) -> None:
        """Keep normal preflight concise and avoid leaking failed cache hints."""
        text_result = self.run_cli(DOCTOR, "--repo", self.repo)
        self.assertEqual(1, len(text_result.stdout.splitlines()))
        json_result = self.run_cli(DOCTOR, "--repo", self.repo, "--json")
        payload = json.loads(json_result.stdout)
        self.assertEqual("project-workflow/doctor/v1", payload["schema"])
        self.assertEqual("UNKNOWN", payload["native_agents"]["status"])
        self.assertIsNone(payload["native_agents"]["capacity"])
        self.assertEqual([], payload["issues"])
        self.assertNotIn("plugins/cache", text_result.stdout + text_result.stderr)

        stale_hint = self.repo / "missing-plugin-cache-version"
        recovered = self.run_cli(
            DOCTOR,
            "--repo",
            self.repo,
            "--plugin-root",
            stale_hint,
            "--json",
        )
        recovered_payload = json.loads(recovered.stdout)
        self.assertTrue(recovered_payload["plugin"]["recovered"])
        self.assertNotIn(str(stale_hint), recovered.stdout + recovered.stderr)

    def test_doctor_blocker_is_stable_and_does_not_leak_traceback(self) -> None:
        """Return a structured blocker when the state directory cannot be created."""
        state_parent = self.repo / ".codex"
        state_parent.mkdir()
        (state_parent / "project-workflow").write_text(
            "not a directory", encoding="utf-8"
        )
        failure = self.run_cli(
            DOCTOR,
            "--repo",
            self.repo,
            "--json",
            expected=2,
        )
        payload = json.loads(failure.stdout)
        self.assertEqual("BLOCKED", payload["status"])
        self.assertIn(
            "STATE_DIRECTORY_NOT_WRITABLE",
            {issue["code"] for issue in payload["issues"]},
        )
        self.assertNotIn("Traceback", failure.stderr)


if __name__ == "__main__":
    unittest.main()
