"""Independent black-box contracts for Project Workflow final safety gates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PLUGIN_ROOT / "scripts" / "workflow_state.py"
ORCHESTRATION = PLUGIN_ROOT / "scripts" / "orchestration_state.py"
DOCTOR = PLUGIN_ROOT / "scripts" / "project_workflow_doctor.py"
SNAPSHOT = PLUGIN_ROOT / "scripts" / "filesystem_snapshot.py"


class FinalGateContractTest(unittest.TestCase):
    """Exercise public CLIs without importing production implementation details."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()
        self.plan = self.repo / "plan.md"
        self.plan.write_text("# Contract plan\n\nIndependent acceptance.\n", encoding="utf-8")
        self.state = (
            self.repo
            / ".codex/project-workflow/final-contract/orchestration.json"
        )

    def run_cli(
        self,
        script: Path,
        *arguments: str,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        """Run one public helper and enforce its stable process result."""
        result = subprocess.run(
            [sys.executable, str(script), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def workflow(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the lifecycle CLI."""
        return self.run_cli(WORKFLOW, *arguments, expected=expected)

    def orchestration(
        self, *arguments: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        """Run the scheduler CLI."""
        return self.run_cli(ORCHESTRATION, *arguments, expected=expected)

    def initialize_plan(self, *, orchestration: bool = True) -> None:
        """Create a LIGHT/NONE plan at the execution boundary."""
        self.workflow(
            "init",
            str(self.plan),
            "--plan-id",
            "final-contract",
            "--repo",
            str(self.repo),
            "--vcs-mode",
            "NONE",
        )
        additions = [
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            "filesystem_snapshot_scopes: []",
            "filesystem_snapshot_excludes: []",
            'filesystem_write_scopes: ["plan.md", "scope-t01"]',
        ]
        if orchestration:
            additions.extend(
                [
                    'execution_mode: "SINGLE_AGENT"',
                    "max_workers: 1",
                    'agent_topology: "SHARED_WORKSPACE"',
                    'orchestration_state: ".codex/project-workflow/final-contract/orchestration.json"',
                ]
            )
        self.add_metadata(*additions)
        self.workflow(
            "start-execution",
            str(self.plan),
            "--repo",
            str(self.repo),
            "--confirmation",
            "开始执行 final-contract revision 1",
            "--at",
            "2026-08-25T08:00:00+08:00",
        )

    def add_metadata(self, *lines: str) -> None:
        """Add public plan fields without depending on parser internals."""
        text = self.plan.read_text(encoding="utf-8")
        marker = "---\n\n# Contract plan"
        self.assertIn(marker, text)
        text = text.replace(marker, "\n".join(lines) + "\n" + marker, 1)
        self.plan.write_text(text, encoding="utf-8")

    def task(self, *, status: str = "COMPLETED", task_id: str = "T01") -> dict[str, object]:
        """Return one scheduler task using the documented v1 fields."""
        completed = status == "COMPLETED"
        return {
            "id": task_id,
            "display_name": f"Contract {task_id}",
            "status": status,
            "depends_on": [],
            "write_scope": ["plan.md", f"scope-{task_id.lower()}"],
            "agent_eligible": False,
            "owner": "coordinator",
            "started_at": "2026-08-25T00:00:01+00:00",
            "attempts": 1,
            "evidence": ["black-box accepted"] if completed else [],
            "block_reason": "",
            "parallel_group": "",
            "planned_owner": "",
            "branch_or_worktree": "",
            "assignment_kind": "COORDINATOR",
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "spawn_status": "",
            "spawned_at": "",
            "finished_at": "",
            "runtime_verification": "",
        }

    def state_document(
        self,
        *,
        status: str = "COMPLETED",
        state_version: int | None = 11,
        plan_id: str = "final-contract",
    ) -> dict[str, object]:
        """Return a documented orchestration/v1 companion document."""
        state: dict[str, object] = {
            "schema": "project-workflow/orchestration/v1",
            "plan_id": plan_id,
            "revision": 1,
            "execution_mode": "SINGLE_AGENT",
            "max_workers": 1,
            "max_attempts": 2,
            "topology": "SHARED_WORKSPACE",
            "policy_contract": "v0.4",
            "tasks": [self.task(status=status)],
            "events": [],
        }
        if state_version is not None:
            state["state_version"] = state_version
        return state

    def write_state(self, document: dict[str, object] | None = None) -> None:
        """Persist a companion state in the approved internal location."""
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(
            json.dumps(document or self.state_document()), encoding="utf-8"
        )

    def write_baseline(self, *scopes: str) -> None:
        """Create the documented NONE baseline for final completion evidence."""
        for scope in scopes:
            (self.repo / scope).mkdir(parents=True, exist_ok=True)
        self.run_cli(
            SNAPSHOT,
            "create",
            "--repo",
            str(self.repo),
            "--output",
            ".codex/project-workflow/final-contract/filesystem-baseline.json",
            *(argument for scope in scopes for argument in ("--scope", scope)),
        )

    def inspect_plan(self) -> dict[str, object]:
        """Read normalized plan state through the public CLI."""
        return json.loads(self.workflow("inspect", str(self.plan)).stdout)

    def test_complete_is_atomic_and_binds_exact_companion_version(self) -> None:
        """Reject absent, unfinished, or mismatched evidence before one valid completion."""
        self.initialize_plan()
        original = self.plan.read_bytes()

        self.workflow("complete", str(self.plan), "--repo", str(self.repo), expected=2)
        self.assertEqual(original, self.plan.read_bytes())

        for document in (
            self.state_document(status="ASSIGNED"),
            self.state_document(plan_id="another-plan"),
            {**self.state_document(), "revision": 2},
        ):
            with self.subTest(document=document):
                self.write_state(document)
                self.workflow(
                    "complete", str(self.plan), "--repo", str(self.repo), expected=2
                )
                self.assertEqual(original, self.plan.read_bytes())

        self.write_state(self.state_document(state_version=37))
        self.workflow("complete", str(self.plan), "--repo", str(self.repo))
        metadata = self.inspect_plan()
        self.assertEqual("COMPLETED", metadata["phase"])
        self.assertEqual(37, metadata["final_orchestration_state_version"])

    def test_persisted_approval_scalars_and_times_fail_closed(self) -> None:
        """Reject YAML coercions, containers, blanks, and timezone-less approval records."""
        self.initialize_plan()
        valid = self.plan.read_text(encoding="utf-8")
        mutations = {
            "numeric confirmation": ('confirmation_record: "开始执行 final-contract revision 1"', "confirmation_record: 7"),
            "container confirmation": ('confirmation_record: "开始执行 final-contract revision 1"', "confirmation_record: [confirm]"),
            "blank confirmation": ('confirmation_record: "开始执行 final-contract revision 1"', "confirmation_record:"),
            "numeric time": ('approved_at: "2026-08-25T08:00:00+08:00"', "approved_at: 7"),
            "container time": ('approved_at: "2026-08-25T08:00:00+08:00"', "approved_at: [time]"),
            "naive time": ('approved_at: "2026-08-25T08:00:00+08:00"', "approved_at: '2026-08-25T08:00:00'"),
            "illegal timezone": ('approved_at: "2026-08-25T08:00:00+08:00"', "approved_at: '2026-08-25T08:00:00+25:00'"),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label):
                self.assertIn(old, valid)
                self.plan.write_text(valid.replace(old, new, 1), encoding="utf-8")
                before = self.plan.read_bytes()
                self.workflow("resume", str(self.plan), "--repo", str(self.repo), expected=2)
                self.assertEqual(before, self.plan.read_bytes())
        self.plan.write_text(valid, encoding="utf-8")

    def test_concurrent_conflicting_confirmations_have_exactly_one_winner(self) -> None:
        """Serialize approval so competing user messages cannot both be persisted."""
        self.workflow(
            "init", str(self.plan), "--plan-id", "final-contract", "--repo", str(self.repo),
            "--vcs-mode", "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            "filesystem_snapshot_scopes: []",
            "filesystem_snapshot_excludes: []",
            'filesystem_write_scopes: ["plan.md"]',
        )
        commands = [
            [
                sys.executable, str(WORKFLOW), "start-execution", str(self.plan),
                "--repo", str(self.repo), "--confirmation", confirmation,
                "--at", "2026-08-25T00:00:00+00:00",
            ]
            for confirmation in ("确认甲", "确认乙")
        ]
        processes = [
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for command in commands
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual([0, 2], sorted(result[2] for result in results))
        metadata = self.inspect_plan()
        self.assertEqual("IN_PROGRESS", metadata["phase"])
        self.assertIn(metadata["confirmation_record"], {"确认甲", "确认乙"})

    def test_resume_is_no_write_for_running_and_replays_blocked_gate(self) -> None:
        """Keep active resume idempotent and require valid approval to leave BLOCKED."""
        self.initialize_plan(orchestration=False)
        before = self.plan.read_bytes()
        self.workflow("resume", str(self.plan), "--repo", str(self.repo))
        self.assertEqual(before, self.plan.read_bytes())

        self.workflow("transition", str(self.plan), "BLOCKED")
        blocked = self.plan.read_text(encoding="utf-8")
        invalid = blocked.replace("approved_revision: 1", "approved_revision: 2", 1)
        self.plan.write_text(invalid, encoding="utf-8")
        invalid_bytes = self.plan.read_bytes()
        self.workflow("resume", str(self.plan), "--repo", str(self.repo), expected=2)
        self.assertEqual(invalid_bytes, self.plan.read_bytes())

        self.plan.write_text(blocked, encoding="utf-8")
        self.workflow("resume", str(self.plan), "--repo", str(self.repo))
        self.assertEqual("IN_PROGRESS", self.inspect_plan()["phase"])

    def test_repo_boundary_and_external_historical_state_are_read_only(self) -> None:
        """Allow diagnostics for legacy state while denying every escaped mutation."""
        self.initialize_plan(orchestration=False)
        outside_plan = Path(self.temporary_directory.name) / "outside.md"
        outside_plan.write_text(self.plan.read_text(encoding="utf-8"), encoding="utf-8")
        outside_before = outside_plan.read_bytes()
        self.workflow(
            "resume", str(outside_plan), "--repo", str(self.repo), expected=2
        )
        self.assertEqual(outside_before, outside_plan.read_bytes())

        legacy = self.repo / "legacy/orchestration.json"
        legacy.parent.mkdir()
        legacy.write_text(json.dumps(self.state_document()), encoding="utf-8")
        self.orchestration(
            "validate", str(legacy), "--plan", str(self.plan), "--repo", str(self.repo)
        )
        legacy_before = legacy.read_bytes()
        self.orchestration(
            "assign", str(legacy), "T01", "--owner", "coordinator", "--coordinator",
            "--plan", str(self.plan), "--repo", str(self.repo), expected=2,
        )
        self.assertEqual(legacy_before, legacy.read_bytes())

    def test_legacy_state_version_migrates_once_only_inside_internal_root(self) -> None:
        """Read absent state_version as zero and increment on the first legal mutation."""
        self.initialize_plan(orchestration=False)
        pending = self.state_document(status="PENDING", state_version=None)
        pending["tasks"][0]["owner"] = ""
        pending["tasks"][0]["started_at"] = ""
        pending["tasks"][0]["attempts"] = 0
        pending["tasks"][0]["assignment_kind"] = ""
        self.write_state(pending)
        inspected = json.loads(
            self.orchestration(
                "inspect", str(self.state), "--repo", str(self.repo)
            ).stdout
        )
        self.assertEqual(0, inspected["state_version"])
        self.orchestration(
            "assign", str(self.state), "T01", "--owner", "coordinator", "--coordinator",
            "--expected-version", "0", "--plan", str(self.plan), "--repo", str(self.repo),
        )
        self.assertEqual(1, json.loads(self.state.read_text(encoding="utf-8"))["state_version"])

    def test_scheduler_rejects_alias_scopes_duplicate_workers_and_bad_times(self) -> None:
        """Fail closed on ambiguous paths, active identities, and unzoned history."""
        self.initialize_plan(orchestration=False)
        invalid_scopes = ("./src", "src//main", "src/../secret", "/tmp/out", "C:/temp", "src\\main")
        for scope in invalid_scopes:
            with self.subTest(scope=scope):
                document = self.state_document(status="PENDING")
                document["tasks"][0]["write_scope"] = [scope]
                self.write_state(document)
                self.orchestration(
                    "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo),
                    expected=2,
                )

        document = self.state_document(status="ASSIGNED")
        first = document["tasks"][0]
        first.update(
            {
                "agent_eligible": True,
                "owner": "worker-one",
                "assignment_kind": "WORKER",
                "runtime_agent_id": "same-agent",
                "runtime_task_name": "/root/same-worker",
                "spawn_status": "RUNNING",
                "spawned_at": "2026-08-25T00:00:02+00:00",
                "runtime_verification": "VERIFIED",
            }
        )
        second = {**first, "id": "T02", "display_name": "Contract T02", "write_scope": ["scope-t02"]}
        document.update({"execution_mode": "AUTO_MULTI_AGENT", "max_workers": 2, "tasks": [first, second]})
        self.write_state(document)
        self.orchestration(
            "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo), expected=2
        )

    def test_equivalent_unicode_and_mac_case_scopes_cannot_run_together(self) -> None:
        """Treat filesystem-equivalent spellings as one active ownership boundary."""
        self.initialize_plan(orchestration=False)
        scope_pairs = [
            ("src/Caf\u00e9", unicodedata.normalize("NFD", "src/Caf\u00e9")),
        ]
        if sys.platform == "darwin":
            scope_pairs.append(("src/Module", "src/module"))

        for first_scope, second_scope in scope_pairs:
            with self.subTest(first=first_scope, second=second_scope):
                document = self.state_document(status="ASSIGNED")
                first = document["tasks"][0]
                first["write_scope"] = [first_scope]
                second = {
                    **first,
                    "id": "T02",
                    "display_name": "Contract T02",
                    "owner": "coordinator-two",
                    "write_scope": [second_scope],
                }
                document.update(
                    {
                        "execution_mode": "AUTO_MULTI_AGENT",
                        "max_workers": 2,
                        "tasks": [first, second],
                    }
                )
                self.write_state(document)
                self.orchestration(
                    "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo),
                    expected=2,
                )

    def test_historical_completed_worker_and_recognized_event_remain_readable(self) -> None:
        """Normalize old accepted evidence without fabricating a native runtime identity."""
        self.initialize_plan(orchestration=False)
        document = self.state_document()
        document.pop("policy_contract")
        task = document["tasks"][0]
        task.update(
            {
                "agent_eligible": True,
                "owner": "historical-worker",
                "assignment_kind": "WORKER",
            }
        )
        for field in (
            "runtime_agent_id", "runtime_task_name", "spawn_status", "spawned_at",
            "finished_at", "runtime_verification",
        ):
            task.pop(field)
        document["events"] = [
            {
                "at": "2026-08-25T00:00:00+00:00",
                "action": "complete",
                "task_id": "T01",
                "owner": "historical-worker",
                "detail": "historical evidence",
            }
        ]
        self.write_state(document)
        self.orchestration(
            "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo)
        )
        inspected = json.loads(
            self.orchestration("inspect", str(self.state), "--repo", str(self.repo)).stdout
        )
        self.assertEqual("UNAVAILABLE", inspected["tasks"][0]["runtime_verification"])
        self.assertEqual("COMPLETED", inspected["tasks"][0]["status"])

    def test_unknown_or_corrupt_orchestration_is_rejected_without_rewrite(self) -> None:
        """Quarantine future states and malformed bytes through read-only failure."""
        self.initialize_plan(orchestration=False)
        unknown = self.state_document()
        unknown["tasks"][0]["status"] = "FUTURE_STATE"
        self.write_state(unknown)
        before = self.state.read_bytes()
        self.orchestration(
            "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo),
            expected=2,
        )
        self.assertEqual(before, self.state.read_bytes())

        self.state.write_bytes(b'{"schema":')
        corrupt = self.state.read_bytes()
        self.orchestration(
            "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo),
            expected=2,
        )
        self.assertEqual(corrupt, self.state.read_bytes())

        document = self.state_document(status="ASSIGNED")
        document["tasks"][0]["started_at"] = "2026-08-25T00:00:00"
        self.write_state(document)
        self.orchestration(
            "validate", str(self.state), "--plan", str(self.plan), "--repo", str(self.repo), expected=2
        )

    def test_doctor_reuses_final_binding_and_rejects_escaped_plan(self) -> None:
        """Require Doctor to agree with the completion gate and repository boundary."""
        self.initialize_plan()
        self.write_state(self.state_document(state_version=19))
        self.workflow("complete", str(self.plan), "--repo", str(self.repo))
        accepted = self.run_cli(
            DOCTOR, "--repo", str(self.repo), "--plan", "plan.md", "--json"
        )
        self.assertEqual("OK", json.loads(accepted.stdout)["plan"]["orchestration_status"])

        changed = json.loads(self.state.read_text(encoding="utf-8"))
        changed["state_version"] = 20
        self.state.write_text(json.dumps(changed), encoding="utf-8")
        blocked = self.run_cli(
            DOCTOR, "--repo", str(self.repo), "--plan", "plan.md", "--json", expected=2
        )
        self.assertIn(
            "FINAL_EVIDENCE_INVALID",
            {issue["code"] for issue in json.loads(blocked.stdout)["issues"]},
        )

        escaped = self.run_cli(
            DOCTOR, "--repo", str(self.repo), "--plan", "../outside.md", "--json", expected=2
        )
        self.assertIn("PLAN_INVALID", {issue["code"] for issue in json.loads(escaped.stdout)["issues"]})

    def test_legacy_plan_without_orchestration_remains_completable(self) -> None:
        """Do not retroactively require scheduler evidence for historical serial plans."""
        self.initialize_plan(orchestration=False)
        text = self.plan.read_text(encoding="utf-8")
        for current_only in (
            'policy_contract: "v0.4"\n',
            'conversation_title: "Contract plan"\n',
            "progress_heartbeat_minutes: 5\n",
            'vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\n',
            'workflow_profile: "LIGHT"\n',
            'rollback_required: "false"\n',
            "filesystem_snapshot_scopes: []\n",
            "filesystem_snapshot_excludes: []\n",
            'filesystem_write_scopes: ["plan.md", "scope-t01"]\n',
        ):
            text = text.replace(current_only, "", 1)
        text = text.replace(
            "---\n\n# Contract plan",
            'rollback_strategy: "restore archived workspace"\n'
            'rollback_evidence: "archive verified"\n'
            'rollback_verification: "VERIFIED"\n---\n\n# Contract plan',
            1,
        )
        self.plan.write_text(text, encoding="utf-8")
        self.workflow("complete", str(self.plan), "--repo", str(self.repo))
        self.assertEqual("COMPLETED", self.inspect_plan()["phase"])


if __name__ == "__main__":
    unittest.main()
