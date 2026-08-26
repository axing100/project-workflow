"""Tests for the Project Workflow multi-agent orchestration helper."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATION_SCRIPT = PLUGIN_ROOT / "scripts" / "orchestration_state.py"
WORKFLOW_SCRIPT = PLUGIN_ROOT / "scripts" / "workflow_state.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import orchestration_state as orchestration_module


class OrchestrationStateTest(unittest.TestCase):
    """Verify task DAG validation, scheduling, conflicts, and recovery."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.repo = root
        self.plan = root / "plan.md"
        self.state = root / ".codex/project-workflow/scheduler-test/orchestration.json"
        self.state.parent.mkdir(parents=True)
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
            "display_name": task_id,
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
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "spawn_status": "",
            "spawned_at": "",
            "finished_at": "",
            "runtime_verification": "",
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

    def add_plan_metadata(self, *lines: str) -> None:
        """Append supported metadata to the generated plan frontmatter."""
        text = self.plan.read_text(encoding="utf-8")
        marker = "---\n\n# Plan"
        replacement = "".join(f"{line}\n" for line in lines) + marker
        self.assertIn(marker, text)
        self.plan.write_text(text.replace(marker, replacement, 1), encoding="utf-8")

    def set_plan_phase(self, phase: str) -> None:
        """Set a fixture phase without exercising the separate lifecycle helper."""
        text = self.plan.read_text(encoding="utf-8")
        self.assertIn('phase: "IN_PROGRESS"', text)
        self.plan.write_text(
            text.replace('phase: "IN_PROGRESS"', f'phase: "{phase}"', 1),
            encoding="utf-8",
        )

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
            "--repo",
            str(self.repo),
            expected=expected,
        )

    def activate_worker(self, task_id: str, owner: str) -> str:
        """Reserve and bind one task to a deterministic native worker identity."""
        runtime_agent_id = f"agent-{task_id.lower()}"
        self.orchestration("assign", task_id, "--owner", owner)
        self.orchestration(
            "activate",
            task_id,
            "--runtime-agent-id",
            runtime_agent_id,
            "--runtime-task-name",
            owner,
        )
        return runtime_agent_id

    def test_validate_and_ready_wave(self) -> None:
        """Return independent root tasks as the first safe wave."""
        self.orchestration("validate", "--require-approval")
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T01", "T02"], [item["id"] for item in json.loads(result.stdout)])

    def test_benefit_gate_rejects_low_savings_and_accepts_high_savings(self) -> None:
        """Schedule estimated work only when parallel savings reaches the approved threshold."""
        state = self.default_state()
        state["parallelism_policy"] = "BENEFIT_GATED"
        for task in state["tasks"][:2]:
            task["estimated_minutes"] = 10
            task["coordination_minutes"] = 4
        self.write_state(state)
        low = self.orchestration("ready", "--agent-only")
        self.assertEqual([], json.loads(low.stdout))

        state = self.default_state()
        state["parallelism_policy"] = "BENEFIT_GATED"
        for task in state["tasks"][:2]:
            task["estimated_minutes"] = 10
            task["coordination_minutes"] = 1
        self.write_state(state)
        high = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T01", "T02"], [item["id"] for item in json.loads(high.stdout)])

    def test_benefit_gate_allows_isolated_contract_verifier(self) -> None:
        """Allow a single independent verifier as the quality-isolation exception."""
        state = self.default_state()
        verifier = self.default_task("T01", [], ["tests/contract"])
        verifier.update(
            {
                "role": "CONTRACT_VERIFIER",
                "independent_verification": True,
                "estimated_minutes": 15,
                "coordination_minutes": 2,
            }
        )
        state["tasks"] = [verifier]
        state["parallelism_policy"] = "BENEFIT_GATED"
        self.write_state(state)
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual(["T01"], [item["id"] for item in json.loads(result.stdout)])

    def test_benefit_gate_rejects_unknown_or_zero_estimates(self) -> None:
        """Fall back to coordinator execution when savings cannot be proven."""
        state = self.default_state()
        state["parallelism_policy"] = "BENEFIT_GATED"
        state["tasks"][0].update({"estimated_minutes": 0, "coordination_minutes": 1})
        state["tasks"][1].update({"estimated_minutes": 10, "coordination_minutes": 1})
        self.write_state(state)
        result = self.orchestration("ready", "--agent-only")
        self.assertEqual([], json.loads(result.stdout))

    def test_benefit_gate_selects_lower_coordination_subset(self) -> None:
        """Choose a beneficial compatible subset instead of the longest costly pair."""
        state = self.default_state()
        state["max_workers"] = 2
        state["parallelism_policy"] = "BENEFIT_GATED"
        state["tasks"] = [
            self.default_task("T01", [], ["module-a"]),
            self.default_task("T02", [], ["module-b"]),
            self.default_task("T03", [], ["module-c"]),
        ]
        state["tasks"][0].update({"estimated_minutes": 100, "coordination_minutes": 0})
        state["tasks"][1].update({"estimated_minutes": 90, "coordination_minutes": 100})
        state["tasks"][2].update({"estimated_minutes": 80, "coordination_minutes": 0})
        self.write_state(state)

        result = self.orchestration("ready", "--agent-only")

        self.assertEqual(["T01", "T03"], [item["id"] for item in json.loads(result.stdout)])

    def test_assign_enforces_benefit_approved_wave(self) -> None:
        """Prevent direct assignment from bypassing the persisted benefit policy."""
        state = self.default_state()
        state["parallelism_policy"] = "BENEFIT_GATED"
        for task in state["tasks"][:2]:
            task.update({"estimated_minutes": 10, "coordination_minutes": 4})
        self.write_state(state)
        failure = self.orchestration(
            "assign",
            "T01",
            "--owner",
            "worker-one",
            expected=2,
        )
        self.assertIn("benefit-approved worker wave", failure.stderr)
        self.assertEqual("PENDING", self.read_state()["tasks"][0]["status"])

        state = self.default_state()
        state["parallelism_policy"] = "BENEFIT_GATED"
        for task in state["tasks"][:2]:
            task.update({"estimated_minutes": 10, "coordination_minutes": 1})
        self.write_state(state)
        self.orchestration("assign", "T01", "--owner", "worker-one")
        self.orchestration("assign", "T02", "--owner", "worker-two")

    def test_independent_verifier_scope_must_not_overlap_implementation(self) -> None:
        """Preserve black-box isolation by rejecting shared writable paths."""
        state = self.default_state()
        state["tasks"][1].update(
            {
                "write_scope": ["module-a"],
                "role": "CONTRACT_VERIFIER",
                "independent_verification": True,
            }
        )
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("contract verifier", failure.stderr)

    def test_full_v04_contract_requires_independent_verifier(self) -> None:
        """Reject newly initialized FULL policy state without isolated verification."""
        self.add_plan_metadata('workflow_profile: "FULL"')
        state = self.default_state()
        state["policy_contract"] = "v0.4"
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("requires an independent contract verifier", failure.stderr)

        state = self.default_state()
        state["policy_contract"] = "v0.4"
        state["tasks"][0].update(
            {"role": "CONTRACT_VERIFIER", "independent_verification": True}
        )
        self.write_state(state)
        self.orchestration("validate")

    def test_missing_profile_is_treated_as_full_for_new_state(self) -> None:
        """Apply the documented FULL default when a v0.4 plan omits its profile."""
        state = self.default_state()
        state["policy_contract"] = "v0.4"
        self.write_state(state)

        failure = self.orchestration("validate", expected=2)

        self.assertIn("requires an independent contract verifier", failure.stderr)

    def test_policy_numbers_reject_boolean_and_extreme_values(self) -> None:
        """Do not accept Python booleans or impractical scheduler limits as integers."""
        state = self.default_state()
        state["max_workers"] = True
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("max_workers must be an integer", failure.stderr)

        state = self.default_state()
        state["max_attempts"] = 10**100
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("max_attempts must be an integer", failure.stderr)

        state = self.default_state()
        state["tasks"][0]["attempts"] = True
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("attempts for T01 must be a non-negative integer", failure.stderr)

    def test_init_creates_hidden_state_from_compact_tasks(self) -> None:
        """Create scheduler JSON through the helper instead of a reviewed file edit."""
        self.state.unlink()
        self.add_plan_metadata(
            'workflow_profile: "STANDARD"',
            'execution_mode: "AUTO_MULTI_AGENT"',
            "max_workers: 2",
            'agent_topology: "SHARED_WORKSPACE"',
        )
        first = {
            "id": "T01",
            "display_name": "Backend report",
            "depends_on": [],
            "write_scope": ["backend"],
            "agent_eligible": True,
        }
        second = {
            "id": "T02",
            "display_name": "Frontend report",
            "depends_on": [],
            "write_scope": ["frontend"],
            "agent_eligible": True,
        }
        self.run_command(
            "init",
            str(self.state),
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
            "--task",
            json.dumps(first),
            "--task",
            json.dumps(second),
        )
        state = self.read_state()
        self.assertEqual("scheduler-test", state["plan_id"])
        self.assertEqual(["Backend report", "Frontend report"], [
            task["display_name"] for task in state["tasks"]
        ])

    def test_final_validation_accepts_completed_plan_only(self) -> None:
        """Keep final validation available after the lifecycle has completed."""
        state = self.default_state()
        for task in state["tasks"]:
            task["status"] = "COMPLETED"
            task["evidence"] = ["accepted"]
        self.write_state(state)
        self.set_plan_phase("COMPLETED")
        self.orchestration("validate", "--final")
        failure = self.orchestration("validate", "--require-approval", expected=2)
        self.assertIn("found COMPLETED", failure.stderr)

    def test_final_validation_accepts_in_progress_plan_before_completion(self) -> None:
        """Validate scheduler evidence before atomically completing the plan."""
        state = self.default_state()
        for task in state["tasks"]:
            task["status"] = "COMPLETED"
            task["evidence"] = ["accepted"]
        self.write_state(state)
        self.orchestration("validate", "--final")

    def test_final_validation_rejects_incomplete_tasks(self) -> None:
        """Require scheduler completion evidence at the final lifecycle gate."""
        self.set_plan_phase("COMPLETED")
        failure = self.orchestration("validate", "--final", expected=2)
        self.assertIn("requires completed tasks", failure.stderr)

    def test_write_scope_rejects_non_canonical_posix_aliases(self) -> None:
        """Reject aliases instead of silently rewriting scheduler ownership boundaries."""
        invalid_scopes = (
            ".",
            "./module-a",
            "module-a/./service",
            "module-a//service",
            "module-a/../service",
            "module-a/",
            "/module-a",
            "C:/module-a",
            "C:\\module-a",
            "module-a\\service",
        )
        for scope in invalid_scopes:
            with self.subTest(scope=scope):
                state = self.default_state()
                state["tasks"][0]["write_scope"] = [scope]
                self.write_state(state)
                failure = self.orchestration("validate", expected=2)
                self.assertIn("write_scope", failure.stderr)

    def test_unicode_equivalent_active_scopes_conflict(self) -> None:
        """Treat canonically equivalent Unicode paths as one repository scope."""
        state = self.default_state()
        composed = "src/Café"
        decomposed = unicodedata.normalize("NFD", composed)
        state["tasks"] = [
            self.default_task("T01", [], [composed]),
            self.default_task("T02", [], [decomposed]),
        ]
        for index, task in enumerate(state["tasks"]):
            task.update(
                {
                    "status": "ASSIGNED",
                    "owner": f"coordinator-{index}",
                    "started_at": "2026-08-25T00:00:00+00:00",
                    "assignment_kind": "COORDINATOR",
                }
            )
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("write scopes overlap", failure.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "macOS volume semantics")
    def test_case_equivalent_active_scopes_conflict_on_default_mac_volume(self) -> None:
        """Prevent concurrent ownership through case aliases on default macOS volumes."""
        state = self.default_state()
        state["tasks"] = [
            self.default_task("T01", [], ["src/Module"]),
            self.default_task("T02", [], ["src/module"]),
        ]
        for index, task in enumerate(state["tasks"]):
            task.update(
                {
                    "status": "ASSIGNED",
                    "owner": f"coordinator-{index}",
                    "started_at": "2026-08-25T00:00:00+00:00",
                    "assignment_kind": "COORDINATOR",
                }
            )
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("write scopes overlap", failure.stderr)

    def test_external_historical_state_is_read_only_with_repo_context(self) -> None:
        """Allow historical diagnosis outside the internal root but reject mutation."""
        external = self.repo / "legacy.orchestration.json"
        external.write_text(json.dumps(self.default_state()), encoding="utf-8")
        self.run_command(
            "validate",
            str(external),
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
        )
        before = external.read_bytes()
        failure = self.run_command(
            "block",
            str(external),
            "T01",
            "--reason",
            "must migrate",
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
            expected=2,
        )
        self.assertIn("read-only", failure.stderr)
        self.assertEqual(before, external.read_bytes())

    def test_init_rejects_new_external_state(self) -> None:
        """Create new scheduler state only in the repository-owned internal root."""
        external = self.repo / "new-state.json"
        task = {
            "id": "T01",
            "depends_on": [],
            "write_scope": ["src"],
            "agent_eligible": True,
        }
        failure = self.run_command(
            "init",
            str(external),
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
            "--task",
            json.dumps(task),
            expected=2,
        )
        self.assertIn("read-only", failure.stderr)
        self.assertFalse(external.exists())

    def test_internal_mutation_keeps_legacy_cli_without_repo_option(self) -> None:
        """Infer the plan directory only for an already-internal public state path."""
        self.run_command(
            "block",
            str(self.state),
            "T01",
            "--reason",
            "legacy CLI",
            "--plan",
            str(self.plan),
        )
        self.assertEqual("BLOCKED", self.read_state()["tasks"][0]["status"])

    def test_repo_context_rejects_plan_escape(self) -> None:
        """Keep plan linkage inside the explicitly selected repository."""
        outside = self.repo.parent / "outside-plan.md"
        outside.write_text(self.plan.read_text(encoding="utf-8"), encoding="utf-8")
        failure = self.run_command(
            "validate",
            str(self.state),
            "--plan",
            str(outside),
            "--repo",
            str(self.repo),
            expected=2,
        )
        self.assertIn("plan must be inside repository", failure.stderr)

    def test_mutation_rejects_symlinked_internal_state_parent(self) -> None:
        """Repeat parent checks before locks and state replacement writes."""
        state_root = self.repo / ".codex/project-workflow"
        moved_root = self.repo / "saved-project-workflow"
        state_root.rename(moved_root)
        outside = self.repo / "outside-state"
        outside.mkdir()
        state_root.symlink_to(outside, target_is_directory=True)

        failure = self.run_command(
            "block",
            str(self.state),
            "T01",
            "--reason",
            "unsafe parent",
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
            expected=2,
        )
        self.assertIn("must not contain symlinks", failure.stderr)
        self.assertEqual([], list(outside.iterdir()))

    def test_locked_parent_swap_cannot_redirect_state_write(self) -> None:
        """Keep the complete mutation on the directory opened before locking."""
        state_root = self.repo / ".codex/project-workflow"
        moved_root = self.repo / "trusted-project-workflow"
        outside = self.repo / "outside-state"
        outside.mkdir()
        outside_state = outside / "scheduler-test/orchestration.json"
        outside_state.parent.mkdir()
        original_outside = self.state.read_bytes()
        outside_state.write_bytes(original_outside)
        real_open = os.open
        swapped = False

        def swap_before_temporary_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal swapped
            name = os.fspath(path)
            basename = os.path.basename(name)
            if (
                not swapped
                and basename.startswith(".orchestration.json.")
                and not basename.endswith(".lock")
            ):
                state_root.rename(moved_root)
                state_root.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        arguments = [
            str(ORCHESTRATION_SCRIPT),
            "block",
            str(self.state),
            "T01",
            "--reason",
            "parent swapped after lock",
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
        ]
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            orchestration_module.os, "open", side_effect=swap_before_temporary_open
        ):
            self.assertEqual(0, orchestration_module.main())

        trusted_state = moved_root / "scheduler-test/orchestration.json"
        self.assertTrue(swapped)
        self.assertEqual(original_outside, outside_state.read_bytes())
        self.assertEqual(
            "BLOCKED",
            json.loads(trusted_state.read_text(encoding="utf-8"))["tasks"][0]["status"],
        )

    def test_repo_inspect_reads_from_held_internal_directory(self) -> None:
        """Keep explicit-repository reads on the directory opened before dispatch."""
        state_root = self.repo / ".codex/project-workflow"
        moved_root = self.repo / "trusted-project-workflow"
        outside = self.repo / "outside-state"
        outside_state = outside / "scheduler-test/orchestration.json"
        outside_state.parent.mkdir(parents=True)
        untrusted = self.default_state()
        untrusted["plan_id"] = "redirected-outside"
        outside_state.write_text(json.dumps(untrusted), encoding="utf-8")
        original_inspect = orchestration_module.command_inspect

        def swap_before_inspect(args: object) -> None:
            state_root.rename(moved_root)
            state_root.symlink_to(outside, target_is_directory=True)
            original_inspect(args)

        arguments = [
            str(ORCHESTRATION_SCRIPT),
            "inspect",
            str(self.state),
            "--repo",
            str(self.repo),
        ]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            orchestration_module,
            "command_inspect",
            side_effect=swap_before_inspect,
        ), redirect_stdout(output):
            self.assertEqual(0, orchestration_module.main())

        self.assertEqual("scheduler-test", json.loads(output.getvalue())["plan_id"])

    def test_active_worker_runtime_identities_are_unique(self) -> None:
        """Reject duplicate native agent IDs and canonical task names independently."""
        for duplicate_field in ("runtime_agent_id", "runtime_task_name"):
            with self.subTest(field=duplicate_field):
                state = self.default_state()
                state["tasks"] = state["tasks"][:2]
                for index, task in enumerate(state["tasks"]):
                    task.update(
                        {
                            "status": "ASSIGNED",
                            "owner": f"worker-{index}",
                            "started_at": "2026-08-25T00:00:00+00:00",
                            "assignment_kind": "WORKER",
                            "runtime_agent_id": f"agent-{index}",
                            "runtime_task_name": f"/root/worker-{index}",
                            "spawn_status": "RUNNING",
                            "spawned_at": "2026-08-25T00:00:01+00:00",
                            "runtime_verification": "VERIFIED",
                        }
                    )
                state["tasks"][1][duplicate_field] = state["tasks"][0][duplicate_field]
                self.write_state(state)
                failure = self.orchestration("validate", expected=2)
                self.assertIn(f"duplicate active {duplicate_field}", failure.stderr)

    def test_task_times_require_timezone_aware_iso8601(self) -> None:
        """Reject naive, malformed, and non-string task timestamps."""
        invalid_values = ("2026-08-25T00:00:00", "2026-08-25T00:00:00+25:00", True)
        for value in invalid_values:
            with self.subTest(value=value):
                state = self.default_state()
                task = state["tasks"][0]
                task.update(
                    {
                        "status": "ASSIGNED",
                        "owner": "coordinator",
                        "started_at": value,
                        "assignment_kind": "COORDINATOR",
                    }
                )
                self.write_state(state)
                failure = self.orchestration("validate", expected=2)
                self.assertIn("started_at", failure.stderr)

    def test_worker_task_times_must_be_monotonic(self) -> None:
        """Reject spawn-before-start and finish-before-spawn scheduler histories."""
        state = self.default_state()
        task = state["tasks"][0]
        task.update(
            {
                "status": "ASSIGNED",
                "owner": "worker",
                "started_at": "2026-08-25T00:00:02+00:00",
                "assignment_kind": "WORKER",
                "runtime_agent_id": "agent-1",
                "runtime_task_name": "/root/worker",
                "spawn_status": "RUNNING",
                "spawned_at": "2026-08-25T00:00:01+00:00",
                "runtime_verification": "VERIFIED",
            }
        )
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("before started_at", failure.stderr)

        task["status"] = "COMPLETED"
        task["evidence"] = ["accepted"]
        task["started_at"] = "2026-08-25T00:00:00+00:00"
        task["spawn_status"] = "COMPLETED"
        task["finished_at"] = "2026-08-25T00:00:00+00:00"
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("before spawned_at", failure.stderr)

    def test_events_require_known_structure_and_timezone_aware_time(self) -> None:
        """Validate current events strictly while preserving recognized legacy events."""
        self.add_plan_metadata('workflow_profile: "STANDARD"')
        current_event = {
            "at": "2026-08-25T00:00:00+00:00",
            "action": "block",
            "task_id": "T01",
            "owner": "worker",
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "detail": "waiting",
        }
        state = self.default_state()
        state["policy_contract"] = "v0.4"
        state["events"] = [current_event]
        self.write_state(state)
        self.orchestration("validate")

        for update in (
            {"at": "2026-08-25T00:00:00"},
            {"detail": ["not", "a", "string"]},
            {"action": "future_action"},
            {"unknown": "field"},
        ):
            with self.subTest(update=update):
                state = self.default_state()
                state["policy_contract"] = "v0.4"
                event = dict(current_event)
                event.update(update)
                state["events"] = [event]
                self.write_state(state)
                failure = self.orchestration("validate", expected=2)
                self.assertIn("events[0]", failure.stderr)

        legacy = self.default_state()
        legacy["events"] = [
            {
                key: value
                for key, value in current_event.items()
                if key not in {"runtime_agent_id", "runtime_task_name"}
            }
        ]
        self.write_state(legacy)
        self.orchestration("validate")

        rollback = self.default_state()
        rollback["policy_contract"] = "v0.4"
        later = dict(current_event)
        later["at"] = "2026-08-25T00:00:02+00:00"
        earlier = dict(current_event)
        earlier["at"] = "2026-08-25T00:00:01+00:00"
        rollback["events"] = [later, earlier]
        self.write_state(rollback)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("chronological", failure.stderr)

    def test_assignment_completion_unlocks_dependency(self) -> None:
        """Complete root tasks before returning their dependent task."""
        agent_a = self.activate_worker("T01", "worker-a")
        agent_b = self.activate_worker("T02", "worker-b")
        self.orchestration(
            "complete", "T01", "--evidence", "tests passed", "--runtime-agent-id", agent_a
        )
        self.orchestration(
            "complete", "T02", "--evidence", "review passed", "--runtime-agent-id", agent_b
        )
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
        runtime_agent_id = self.activate_worker("T01", "worker-a")
        self.orchestration(
            "release",
            "T01",
            "--reason",
            "worker stopped",
            "--runtime-agent-id",
            runtime_agent_id,
            "--stopped-evidence",
            "interrupt confirmed idle",
        )
        self.orchestration("assign", "T01", "--owner", "worker-b")
        task = self.read_state()["tasks"][0]
        self.assertEqual("ASSIGNED", task["status"])
        self.assertEqual(2, task["attempts"])
        self.assertEqual("worker-b", task["owner"])

    def test_worker_requires_native_runtime_activation(self) -> None:
        """Do not treat a persisted reservation as a running or completed worker."""
        self.orchestration("assign", "T01", "--owner", "worker-a")
        task = self.read_state()["tasks"][0]
        self.assertEqual("WORKER_PENDING", task["assignment_kind"])
        self.assertEqual("PENDING", task["spawn_status"])
        failure = self.orchestration(
            "complete", "T01", "--evidence", "unverified", expected=2
        )
        self.assertIn("before native worker activation", failure.stderr)

    def test_worker_completion_requires_matching_runtime_identity(self) -> None:
        """Bind completion evidence to the native worker returned by Codex."""
        runtime_agent_id = self.activate_worker("T01", "worker-a")
        failure = self.orchestration(
            "complete",
            "T01",
            "--evidence",
            "tests passed",
            "--runtime-agent-id",
            "another-agent",
            expected=2,
        )
        self.assertIn("matching runtime_agent_id", failure.stderr)
        self.orchestration(
            "complete",
            "T01",
            "--evidence",
            "tests passed",
            "--runtime-agent-id",
            runtime_agent_id,
        )
        task = self.read_state()["tasks"][0]
        self.assertEqual("COMPLETED", task["spawn_status"])
        self.assertEqual("VERIFIED", task["runtime_verification"])
        self.assertTrue(task["finished_at"])

    def test_forged_active_worker_is_rejected(self) -> None:
        """Reject WORKER state that has no native Codex runtime identity."""
        state = self.default_state()
        task = state["tasks"][0]
        task.update(
            {
                "status": "ASSIGNED",
                "owner": "worker-a",
                "started_at": "2026-08-21T00:00:00+00:00",
                "assignment_kind": "WORKER",
            }
        )
        self.write_state(state)
        failure = self.orchestration("validate", expected=2)
        self.assertIn("requires native runtime identity", failure.stderr)

    def test_spawn_failure_releases_reservation_with_event(self) -> None:
        """Release a failed native spawn without leaving a fake worker assignment."""
        self.orchestration("assign", "T01", "--owner", "worker-a")
        self.orchestration(
            "release",
            "T01",
            "--reason",
            "native collaboration unavailable",
            "--spawn-failed",
        )
        state = self.read_state()
        self.assertEqual("PENDING", state["tasks"][0]["status"])
        self.assertEqual("spawn_failed", state["events"][-1]["action"])
        self.assertEqual("worker-a", state["events"][-1]["owner"])

    def test_legacy_completed_worker_is_runtime_unavailable(self) -> None:
        """Preserve historical worker claims without inventing native runtime IDs."""
        state = self.default_state()
        task = state["tasks"][0]
        task.update(
            {
                "status": "COMPLETED",
                "owner": "legacy-worker",
                "started_at": "2026-08-20T00:00:00+00:00",
                "assignment_kind": "WORKER",
                "evidence": ["historical evidence"],
            }
        )
        self.write_state(state)
        result = self.run_command("inspect", str(self.state))
        normalized = json.loads(result.stdout)
        self.assertEqual("UNAVAILABLE", normalized["tasks"][0]["runtime_verification"])

    def test_v04_completed_worker_requires_complete_runtime_evidence(self) -> None:
        """Reject every incomplete native Worker identity field under the v0.4 contract."""
        self.add_plan_metadata('workflow_profile: "STANDARD"')
        required_runtime = {
            "owner": "worker-a",
            "started_at": "2026-08-25T00:00:00+00:00",
            "runtime_agent_id": "agent-t01",
            "runtime_task_name": "/root/worker-a",
            "spawn_status": "COMPLETED",
            "spawned_at": "2026-08-25T00:00:01+00:00",
            "finished_at": "2026-08-25T00:00:02+00:00",
            "runtime_verification": "VERIFIED",
        }
        invalid_values = {
            "owner": "",
            "started_at": "",
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "spawn_status": "UNKNOWN",
            "spawned_at": "",
            "finished_at": "",
            "runtime_verification": "UNAVAILABLE",
        }
        for field, invalid_value in invalid_values.items():
            with self.subTest(field=field):
                state = self.default_state()
                state["policy_contract"] = "v0.4"
                task = state["tasks"][0]
                task.update(
                    {
                        "status": "COMPLETED",
                        "assignment_kind": "WORKER",
                        "evidence": ["accepted"],
                        **required_runtime,
                        field: invalid_value,
                    }
                )
                self.write_state(state)
                failure = self.orchestration("validate", expected=2)
                self.assertIn("completed worker task T01", failure.stderr)

        state = self.default_state()
        state["policy_contract"] = "v0.4"
        state["tasks"][0].update(
            {
                "status": "COMPLETED",
                "assignment_kind": "WORKER",
                "evidence": ["accepted"],
                **required_runtime,
            }
        )
        self.write_state(state)
        self.orchestration("validate")

    def test_block_and_release(self) -> None:
        """Persist a blocker and release it after resolution."""
        self.orchestration("block", "T01", "--reason", "missing contract")
        self.assertEqual("BLOCKED", self.read_state()["tasks"][0]["status"])
        self.orchestration("release", "T01", "--reason", "contract supplied")
        self.assertEqual("PENDING", self.read_state()["tasks"][0]["status"])

    def test_blocked_running_worker_holds_slot_and_scope_until_verified_stop(self) -> None:
        """Do not recycle a running worker's resources before interruption evidence."""
        runtime_agent_id = self.activate_worker("T01", "worker-a")
        self.orchestration("block", "T01", "--reason", "needs user input")
        blocked = self.read_state()["tasks"][0]
        self.assertEqual("BLOCKED", blocked["status"])
        self.assertEqual("RUNNING", blocked["spawn_status"])

        state = self.read_state()
        state["tasks"][1]["write_scope"] = ["module-a/service"]
        self.write_state(state)
        result = self.orchestration("ready", "--agent-only")
        self.assertNotIn("T02", [item["id"] for item in json.loads(result.stdout)])
        failure = self.orchestration(
            "release", "T01", "--reason", "worker stopped", expected=2
        )
        self.assertIn("matching runtime_agent_id", failure.stderr)
        self.orchestration(
            "release",
            "T01",
            "--reason",
            "worker stopped",
            "--runtime-agent-id",
            runtime_agent_id,
            "--stopped-evidence",
            "native interrupt returned idle",
        )
        self.assertEqual("worker_stopped", self.read_state()["events"][-2]["action"])

    def test_state_version_migrates_and_rejects_stale_writer(self) -> None:
        """Treat historical missing versions as zero and expose a narrow CAS gate."""
        self.assertNotIn("state_version", self.read_state())
        self.orchestration(
            "assign", "T01", "--owner", "worker-a", "--expected-version", "0"
        )
        self.assertEqual(1, self.read_state()["state_version"])
        failure = self.orchestration(
            "block",
            "T02",
            "--reason",
            "stale write",
            "--expected-version",
            "0",
            expected=2,
        )
        self.assertIn("state version conflict", failure.stderr)
        self.assertEqual("PENDING", self.read_state()["tasks"][1]["status"])

    def test_concurrent_writers_are_serialized_by_versioned_lock(self) -> None:
        """Allow only one of two same-version writers to commit."""
        base = [sys.executable, str(ORCHESTRATION_SCRIPT), "block", str(self.state)]
        suffix = [
            "--expected-version",
            "0",
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
        ]
        first = subprocess.Popen(
            [*base, "T01", "--reason", "first", *suffix],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        second = subprocess.Popen(
            [*base, "T02", "--reason", "second", *suffix],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        first_output = first.communicate(timeout=10)
        second_output = second.communicate(timeout=10)
        self.assertEqual([0, 2], sorted([first.returncode, second.returncode]))
        errors = "\n".join([first_output[1], second_output[1]])
        self.assertIn("state version conflict", errors)
        state = self.read_state()
        self.assertEqual(1, state["state_version"])
        self.assertEqual(
            1,
            sum(task["status"] == "BLOCKED" for task in state["tasks"][:2]),
        )

    def test_none_plan_rejects_non_shared_topology(self) -> None:
        """Cross-check VCS NONE topology during orchestration validation."""
        state = self.default_state()
        state["topology"] = "ISOLATED_WORKTREE"
        self.write_state(state)
        self.add_plan_metadata('agent_topology: "ISOLATED_WORKTREE"')
        self.plan.write_text(
            self.plan.read_text(encoding="utf-8").replace(
                'resolved_vcs_mode: "GIT"', 'resolved_vcs_mode: "NONE"'
            ),
            encoding="utf-8",
        )
        failure = self.orchestration("validate", expected=2)
        self.assertIn("VCS NONE requires SHARED_WORKSPACE", failure.stderr)

    def test_single_agent_rejects_historical_active_worker(self) -> None:
        """Keep SINGLE_AGENT recovery coordinator-only even for persisted records."""
        runtime_agent_id = self.activate_worker("T01", "worker-a")
        state = self.read_state()
        state["execution_mode"] = "SINGLE_AGENT"
        self.write_state(state)
        self.add_plan_metadata('execution_mode: "SINGLE_AGENT"')
        failure = self.orchestration("validate", expected=2)
        self.assertIn("coordinator-only", failure.stderr)
        self.assertEqual("agent-t01", runtime_agent_id)

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
