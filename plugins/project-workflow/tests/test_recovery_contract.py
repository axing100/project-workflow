"""Independent black-box recovery and migration contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "project-workflow" / "scripts"
WORKFLOW = SCRIPTS / "workflow_state.py"
ORCHESTRATION = SCRIPTS / "orchestration_state.py"
SNAPSHOT = SCRIPTS / "filesystem_snapshot.py"
DOCTOR = SCRIPTS / "project_workflow_doctor.py"


def run_cli(script: Path, *args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run one public helper in a separate process."""
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
    phase: str = "IN_PROGRESS",
    vcs_mode: str = "GIT",
    resolved: str = "GIT",
    topology: str = "SHARED_WORKSPACE",
    historical: bool = False,
    max_workers: int = 1,
) -> str:
    """Build a plan from documented public fields."""
    optional = "" if historical else (
        'workflow_profile: "STANDARD"\n'
        f'vcs_mode: "{vcs_mode}"\n'
        f'resolved_vcs_mode: "{resolved}"\n'
        'rollback_required: "false"\n'
    )
    return f"""---
workflow: "project-workflow/v1"
plan_id: "recovery-plan"
revision: 1
phase: "{phase}"
approved_revision: 1
approved_at: "2026-08-25T00:00:00+00:00"
confirmation_record: "approved"
{optional}execution_mode: "AUTO_MULTI_AGENT"
max_workers: {max_workers}
agent_topology: "{topology}"
parallelism_policy: "BENEFIT_GATED"
minimum_parallel_savings_percent: 20
---

# Recovery plan
"""


def task(
    task_id: str,
    scope: str,
    *,
    depends_on: list[str] | None = None,
    verifier: bool = False,
) -> str:
    """Return one public orchestration task argument."""
    payload = {
            "id": task_id,
            "display_name": task_id,
            "depends_on": depends_on or [],
            "write_scope": [scope],
            "agent_eligible": True,
            "estimated_minutes": 20,
            "coordination_minutes": 1,
            "critical_path": True,
    }
    if verifier:
        payload.update({"role": "CONTRACT_VERIFIER", "independent_verification": True})
    return json.dumps(payload)


class OrchestrationRecoveryContractTests(unittest.TestCase):
    """Verify Worker ownership, CAS, topology, and corrupted-state recovery."""

    def init_state(
        self,
        repo: Path,
        tasks: list[str],
        *,
        topology: str = "SHARED_WORKSPACE",
        max_workers: int = 1,
    ) -> tuple[Path, Path]:
        plan = repo / "plan.md"
        state = repo / ".codex/project-workflow/recovery-plan/orchestration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(plan_text(topology=topology, max_workers=max_workers), encoding="utf-8")
        args: list[object] = ["init", state, "--plan", plan, "--repo", repo]
        for item in tasks:
            args.extend(("--task", item))
        result = run_cli(ORCHESTRATION, *args)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return plan, state

    def inspect(self, state: Path) -> dict[str, object]:
        result = run_cli(ORCHESTRATION, "inspect", state)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_none_rejects_non_shared_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            state = repo / ".codex/project-workflow/recovery-plan/orchestration.json"
            state.parent.mkdir(parents=True)
            plan.write_text(
                plan_text(vcs_mode="NONE", resolved="NONE", topology="ISOLATED_WORKTREE"),
                encoding="utf-8",
            )

            result = run_cli(
                ORCHESTRATION,
                "init",
                state,
                "--plan",
                plan,
                "--repo",
                repo,
                "--task",
                task("T01", "src/a"),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(state.exists())
            self.assertNotIn("Traceback", result.stderr)

    def test_blocked_running_worker_keeps_slot_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan, state = self.init_state(
                repo,
                [task("T01", "shared", verifier=True), task("T02", "other")],
            )
            assigned = run_cli(ORCHESTRATION, "assign", state, "T01", "--plan", plan, "--owner", "worker-one")
            self.assertEqual(0, assigned.returncode, assigned.stderr)
            activated = run_cli(
                ORCHESTRATION,
                "activate",
                state,
                "T01",
                "--plan",
                plan,
                "--runtime-agent-id",
                "agent-1",
                "--runtime-task-name",
                "/root/worker-one",
            )
            self.assertEqual(0, activated.returncode, activated.stderr)
            blocked = run_cli(ORCHESTRATION, "block", state, "T01", "--plan", plan, "--reason", "waiting")
            self.assertEqual(0, blocked.returncode, blocked.stderr)

            inspected = self.inspect(state)
            first = next(item for item in inspected["tasks"] if item["id"] == "T01")
            self.assertEqual("BLOCKED", first["status"])
            self.assertEqual("WORKER", first["assignment_kind"])
            self.assertEqual("agent-1", first["runtime_agent_id"])
            self.assertEqual(["shared"], first["write_scope"])
            ready = run_cli(ORCHESTRATION, "ready", state, "--plan", plan, "--agent-only")
            self.assertEqual(0, ready.returncode, ready.stderr)
            self.assertNotIn("T02", [item["id"] for item in json.loads(ready.stdout)])

    def test_active_worker_release_requires_matching_stopped_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan, state = self.init_state(repo, [task("T01", "src/a", verifier=True)])
            self.assertEqual(0, run_cli(ORCHESTRATION, "assign", state, "T01", "--plan", plan, "--owner", "worker").returncode)
            self.assertEqual(
                0,
                run_cli(
                    ORCHESTRATION,
                    "activate",
                    state,
                    "T01",
                    "--plan",
                    plan,
                    "--runtime-agent-id",
                    "agent-1",
                    "--runtime-task-name",
                    "/root/worker",
                ).returncode,
            )
            before = state.read_bytes()

            missing = run_cli(ORCHESTRATION, "release", state, "T01", "--plan", plan, "--reason", "retry")
            self.assertNotEqual(0, missing.returncode)
            self.assertEqual(before, state.read_bytes())
            wrong = run_cli(
                ORCHESTRATION,
                "release",
                state,
                "T01",
                "--plan",
                plan,
                "--reason",
                "retry",
                "--runtime-agent-id",
                "agent-2",
                "--stopped-evidence",
                "runtime confirmed stopped",
            )
            self.assertNotEqual(0, wrong.returncode)
            self.assertEqual(before, state.read_bytes())

            released = run_cli(
                ORCHESTRATION,
                "release",
                state,
                "T01",
                "--plan",
                plan,
                "--reason",
                "retry",
                "--runtime-agent-id",
                "agent-1",
                "--stopped-evidence",
                "runtime confirmed stopped",
            )
            self.assertEqual(0, released.returncode, released.stdout + released.stderr)
            item = self.inspect(state)["tasks"][0]
            self.assertEqual("PENDING", item["status"])
            self.assertFalse(item["runtime_agent_id"])

    def test_state_version_cas_rejects_stale_writer_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan, state = self.init_state(
                repo,
                [task("T01", "src/a"), task("T02", "src/b")],
                max_workers=2,
            )
            version = self.inspect(state)["state_version"]
            first = run_cli(
                ORCHESTRATION,
                "assign",
                state,
                "T01",
                "--plan",
                plan,
                "--owner",
                "worker-one",
                "--expected-version",
                version,
            )
            self.assertEqual(0, first.returncode, first.stderr)
            after_first = state.read_bytes()

            stale = run_cli(
                ORCHESTRATION,
                "assign",
                state,
                "T02",
                "--plan",
                plan,
                "--owner",
                "worker-two",
                "--expected-version",
                version,
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertEqual(after_first, state.read_bytes())
            self.assertEqual(version + 1, self.inspect(state)["state_version"])

    def test_competing_processes_cannot_both_commit_same_cas_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan, state = self.init_state(
                repo,
                [task("T01", "src/a"), task("T02", "src/b")],
                max_workers=2,
            )
            version = self.inspect(state)["state_version"]
            commands = [
                [
                    sys.executable,
                    str(ORCHESTRATION),
                    "assign",
                    str(state),
                    task_id,
                    "--plan",
                    str(plan),
                    "--owner",
                    owner,
                    "--expected-version",
                    str(version),
                ]
                for task_id, owner in (("T01", "worker-one"), ("T02", "worker-two"))
            ]
            processes = [
                subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for command in commands
            ]
            results = [process.communicate(timeout=15) + (process.returncode,) for process in processes]

            self.assertEqual(1, sum(returncode == 0 for _, _, returncode in results), results)
            self.assertEqual(version + 1, self.inspect(state)["state_version"])
            assigned = [item for item in self.inspect(state)["tasks"] if item["status"] == "ASSIGNED"]
            self.assertEqual(1, len(assigned))

    def test_unknown_historical_task_state_is_rejected_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan, state = self.init_state(repo, [task("T01", "src/a")])
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload["tasks"][0]["status"] = "FUTURE_STATE"
            state.write_text(json.dumps(payload), encoding="utf-8")
            before = state.read_bytes()

            result = run_cli(ORCHESTRATION, "inspect", state)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state.read_bytes())
            self.assertNotIn("Traceback", result.stderr)


class HistoricalRecoveryContractTests(unittest.TestCase):
    """Verify v0.3/v0.4 plans, scheduler state, and snapshots stay readable."""

    def test_historical_plan_defaults_are_normalized_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.md"
            plan.write_text(plan_text(historical=True), encoding="utf-8")
            before = plan.read_bytes()

            result = run_cli(WORKFLOW, "inspect", plan)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(before, plan.read_bytes())
            doctor = run_cli(DOCTOR, "--repo", repo, "--plan", "plan.md", "--json")
            doctor_payload = json.loads(doctor.stdout)
            self.assertEqual("AUTO", doctor_payload["version_control"]["requested"])
            self.assertIn(
                "ROLLBACK_REQUIRED",
                [issue["code"] for issue in doctor_payload["issues"]],
            )

    def test_historical_state_without_version_migrates_once_on_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            helper = OrchestrationRecoveryContractTests()
            plan, state = helper.init_state(repo, [task("T01", "src/a", verifier=True)])
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload.pop("state_version", None)
            state.write_text(json.dumps(payload), encoding="utf-8")

            inspected = run_cli(ORCHESTRATION, "inspect", state)
            self.assertEqual(0, inspected.returncode, inspected.stdout + inspected.stderr)
            self.assertEqual(0, json.loads(inspected.stdout)["state_version"])
            assigned = run_cli(
                ORCHESTRATION,
                "assign",
                state,
                "T01",
                "--plan",
                plan,
                "--owner",
                "worker",
                "--expected-version",
                0,
            )
            self.assertEqual(0, assigned.returncode, assigned.stdout + assigned.stderr)
            final = run_cli(ORCHESTRATION, "inspect", state)
            self.assertEqual(1, json.loads(final.stdout)["state_version"])

    def test_historical_completed_worker_without_runtime_identity_stays_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            helper = OrchestrationRecoveryContractTests()
            plan, state = helper.init_state(repo, [task("T01", "src/a", verifier=True)])
            self.assertEqual(0, run_cli(ORCHESTRATION, "assign", state, "T01", "--plan", plan, "--owner", "worker").returncode)
            self.assertEqual(
                0,
                run_cli(
                    ORCHESTRATION,
                    "activate",
                    state,
                    "T01",
                    "--plan",
                    plan,
                    "--runtime-agent-id",
                    "agent-old",
                    "--runtime-task-name",
                    "/root/old-worker",
                ).returncode,
            )
            completed = run_cli(
                ORCHESTRATION,
                "complete",
                state,
                "T01",
                "--plan",
                plan,
                "--runtime-agent-id",
                "agent-old",
                "--evidence",
                "historical evidence",
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload.pop("policy_contract", None)
            historical_task = payload["tasks"][0]
            for field in (
                "runtime_agent_id",
                "runtime_task_name",
                "spawn_status",
                "spawned_at",
                "finished_at",
                "runtime_verification",
            ):
                historical_task.pop(field, None)
            state.write_text(json.dumps(payload), encoding="utf-8")
            before = state.read_bytes()

            inspected = run_cli(ORCHESTRATION, "inspect", state)

            self.assertEqual(0, inspected.returncode, inspected.stdout + inspected.stderr)
            item = json.loads(inspected.stdout)["tasks"][0]
            self.assertEqual("COMPLETED", item["status"])
            self.assertEqual("UNAVAILABLE", item["runtime_verification"])
            self.assertEqual(before, state.read_bytes())

    def test_historical_snapshot_without_mode_remains_comparable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            tracked = repo / "tracked.txt"
            tracked.write_text("unchanged", encoding="utf-8")
            baseline_path = ".codex/project-workflow/recovery/base.json"
            baseline = repo / baseline_path
            created = run_cli(SNAPSHOT, "create", "--repo", repo, "--output", baseline_path)
            self.assertEqual(0, created.returncode, created.stderr)
            payload = json.loads(baseline.read_text(encoding="utf-8"))
            for metadata in payload["files"]:
                metadata.pop("mode", None)
            baseline.write_text(json.dumps(payload), encoding="utf-8")

            result = run_cli(SNAPSHOT, "compare", "--repo", repo, "--baseline", baseline_path)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            comparison = json.loads(result.stdout)
            self.assertEqual([], comparison["modified"])


class PublicDocumentationContractTests(unittest.TestCase):
    """Keep the documented public command surface aligned with argparse."""

    def test_documented_commands_exist_in_helper_help(self) -> None:
        workflow_help = run_cli(WORKFLOW, "--help")
        orchestration_help = run_cli(ORCHESTRATION, "--help")
        snapshot_help = run_cli(SNAPSHOT, "--help")
        self.assertEqual(0, workflow_help.returncode)
        self.assertEqual(0, orchestration_help.returncode)
        self.assertEqual(0, snapshot_help.returncode)
        for command in ("init", "experience", "start-execution", "resume", "complete", "inspect"):
            self.assertIn(command, workflow_help.stdout)
        for command in ("validate", "ready", "assign", "activate", "complete", "inspect", "release"):
            self.assertIn(command, orchestration_help.stdout)
        for command in ("create", "compare"):
            self.assertIn(command, snapshot_help.stdout)

    def test_documented_safety_flags_are_accepted_by_argparse(self) -> None:
        release_help = run_cli(ORCHESTRATION, "release", "--help")
        compare_help = run_cli(SNAPSHOT, "compare", "--help")
        create_help = run_cli(SNAPSHOT, "create", "--help")
        self.assertIn("--runtime-agent-id", release_help.stdout)
        self.assertIn("--stopped-evidence", release_help.stdout)
        self.assertIn("--spawn-failed", release_help.stdout)
        self.assertIn("--expected-version", release_help.stdout)
        self.assertIn("--report-only", compare_help.stdout)
        self.assertIn("--write-scope", compare_help.stdout)
        self.assertIn("--json-details", create_help.stdout)
        self.assertIn("--exclude", create_help.stdout)


if __name__ == "__main__":
    unittest.main()
