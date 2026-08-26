"""Tests for the Project Workflow preflight Doctor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = PLUGIN_ROOT / "scripts/project_workflow_doctor.py"
WORKFLOW_STATE = PLUGIN_ROOT / "scripts/workflow_state.py"


class ProjectWorkflowDoctorTest(unittest.TestCase):
    """Verify stable output, blocking checks, and quiet path recovery."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()

    def run_doctor(
        self,
        *arguments: str,
        expected: int = 0,
        include_plugin_root: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run Doctor and assert its exit code."""
        command = [sys.executable, str(DOCTOR), "--repo", str(self.repo)]
        if include_plugin_root:
            command.extend(("--plugin-root", str(PLUGIN_ROOT)))
        command.extend(arguments)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def initialize_plan(self) -> Path:
        """Create a valid plan inside the temporary repository."""
        plan = self.repo / "docs/plan/test.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Test plan\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_STATE),
                "init",
                str(plan),
                "--plan-id",
                "doctor-test",
                "--repo",
                str(self.repo),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return plan

    def valid_orchestration(self) -> dict:
        """Return a complete legacy-compatible orchestration state."""
        return {
            "schema": "project-workflow/orchestration/v1",
            "plan_id": "doctor-test",
            "revision": 1,
            "execution_mode": "SINGLE_AGENT",
            "max_workers": 1,
            "topology": "SHARED_WORKSPACE",
            "tasks": [
                {
                    "id": "T01",
                    "status": "PENDING",
                    "depends_on": [],
                    "write_scope": ["src"],
                    "agent_eligible": False,
                    "owner": "",
                    "started_at": "",
                    "attempts": 0,
                    "evidence": [],
                    "block_reason": "",
                }
            ],
        }

    def completed_orchestration(self) -> dict:
        """Return v0.4 final evidence with one completed coordinator task."""
        state = self.valid_orchestration()
        state.update({"policy_contract": "v0.4", "state_version": 4})
        state["tasks"][0].update(
            {
                "status": "COMPLETED",
                "owner": "coordinator",
                "started_at": "2026-08-25T00:00:00+00:00",
                "attempts": 1,
                "evidence": ["verified"],
                "assignment_kind": "COORDINATOR",
            }
        )
        return state

    def mark_plan_completed(self, plan: Path, bound_version: int = 4) -> None:
        """Create a completed plan fixture without invoking the final gate under test."""
        git_init = subprocess.run(
            ["git", "init", "--quiet", str(self.repo)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, git_init.returncode, git_init.stderr)
        content = plan.read_text(encoding="utf-8")
        for current_only in (
            'policy_contract: "v0.4"\n',
            'conversation_title: "Test plan"\n',
            "progress_heartbeat_minutes: 5\n",
            'vcs_mode: "AUTO"\n',
            'resolved_vcs_mode: "NONE"\n',
        ):
            content = content.replace(current_only, "")
        content = content.replace('phase: "AWAITING_CONFIRMATION"', 'phase: "COMPLETED"')
        content = content.replace("approved_revision: \n", "approved_revision: 1\n")
        content = content.replace(
            "approved_at: \n", 'approved_at: "2026-08-25T00:00:00+00:00"\n'
        )
        content = content.replace(
            "confirmation_record: \n", 'confirmation_record: "确认"\n'
        )
        content = content.replace(
            "---\n\n# Test plan",
            'workflow_profile: "LIGHT"\n'
            f"final_orchestration_state_version: {bound_version}\n---\n\n# Test plan",
        )
        plan.write_text(content, encoding="utf-8")

    def approve_plan(self, plan: Path) -> None:
        """Persist a current approval record through the public workflow CLI."""
        result = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_STATE),
                "approve",
                str(plan),
                "--confirmation",
                "确认",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def complete_none_plan(self) -> Path:
        """Create one current NONE plan with immutable final file evidence."""
        plan = self.initialize_plan()
        content = plan.read_text(encoding="utf-8").replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "STANDARD"\n'
            'rollback_required: "false"\n'
            'filesystem_snapshot_scopes: []\n'
            'filesystem_snapshot_excludes: []\n'
            'filesystem_write_scopes: ["docs/plan", "src"]\n',
        )
        plan.write_text(content, encoding="utf-8")
        for command in (
            (
                "start-execution",
                str(plan),
                "--repo",
                str(self.repo),
                "--confirmation",
                "确认",
            ),
            ("complete", str(plan), "--repo", str(self.repo)),
        ):
            result = subprocess.run(
                [sys.executable, str(WORKFLOW_STATE), *command],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        return plan

    def test_json_output_has_stable_checks_and_unknown_native_agents(self) -> None:
        result = self.run_doctor("--json")
        payload = json.loads(result.stdout)
        self.assertEqual("project-workflow/doctor/v1", payload["schema"])
        self.assertEqual("OK", payload["status"])
        self.assertEqual(0, payload["exit_code"])
        self.assertEqual("OK", payload["plugin"]["status"])
        self.assertEqual("OK", payload["python"]["status"])
        self.assertEqual("OK", payload["cli"]["workflow_state"])
        self.assertEqual("OK", payload["cli"]["orchestration_state"])
        self.assertEqual("UNKNOWN", payload["native_agents"]["status"])
        self.assertEqual("AUTO", payload["version_control"]["requested"])
        self.assertEqual("NONE", payload["version_control"]["resolved"])
        self.assertEqual("OK", payload["version_control"]["status"])
        self.assertIsNone(payload["native_agents"]["capacity"])
        self.assertEqual([], payload["issues"])

    def test_explicit_git_blocks_outside_a_git_worktree(self) -> None:
        result = self.run_doctor("--vcs-mode", "GIT", "--json", expected=2)
        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["version_control"]["status"])
        self.assertIn("VCS_MODE_INVALID", {item["code"] for item in payload["issues"]})

    def test_explicit_none_does_not_invoke_git(self) -> None:
        marker = self.repo / "git-invoked"
        binary_directory = self.repo / "bin"
        binary_directory.mkdir()
        fake_git = binary_directory / "git"
        fake_git.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
        fake_git.chmod(0o755)
        environment = dict(os.environ)
        environment["PATH"] = f"{binary_directory}:{environment.get('PATH', '')}"
        result = subprocess.run(
            [
                sys.executable,
                str(DOCTOR),
                "--repo",
                str(self.repo),
                "--plugin-root",
                str(PLUGIN_ROOT),
                "--vcs-mode",
                "NONE",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("NONE", payload["version_control"]["resolved"])
        self.assertFalse(marker.exists())

    def test_plan_vcs_environment_drift_is_blocking(self) -> None:
        plan = self.initialize_plan()
        content = plan.read_text(encoding="utf-8")
        plan.write_text(
            content.replace('resolved_vcs_mode: "NONE"', 'resolved_vcs_mode: "GIT"'),
            encoding="utf-8",
        )
        result = self.run_doctor("--plan", str(plan), "--json", expected=2)
        payload = json.loads(result.stdout)
        self.assertIn(
            "VCS_ENVIRONMENT_DRIFT",
            {item["code"] for item in payload["issues"]},
        )

    def test_approved_light_none_honors_explicit_rollback_requirement(self) -> None:
        """Doctor must use the execution gate even outside the FULL profile."""
        plan = self.initialize_plan()
        content = plan.read_text(encoding="utf-8").replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "LIGHT"\n'
            'rollback_required: "true"\n',
        )
        plan.write_text(content, encoding="utf-8")
        self.approve_plan(plan)

        result = self.run_doctor("--plan", str(plan), "--json", expected=2)

        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["version_control"]["status"])
        self.assertIn("ROLLBACK_REQUIRED", {item["code"] for item in payload["issues"]})

    def test_approved_full_none_requires_all_rollback_evidence_fields(self) -> None:
        """Partial recovery evidence must not satisfy the execution gate."""
        plan = self.initialize_plan()
        content = plan.read_text(encoding="utf-8").replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "FULL"\n'
            'rollback_strategy: "restore snapshot"\n'
            'rollback_evidence: "restore rehearsal"\n',
        )
        plan.write_text(content, encoding="utf-8")
        self.approve_plan(plan)

        result = self.run_doctor("--plan", str(plan), "--json", expected=2)

        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["version_control"]["status"])
        self.assertIn("ROLLBACK_REQUIRED", {item["code"] for item in payload["issues"]})

    def test_missing_experience_command_blocks_stale_plugin(self) -> None:
        """Reject a stale plugin whose workflow CLI predates the experience contract."""
        plugin_root = self.repo / "stale-plugin"
        manifest = plugin_root / ".codex-plugin/plugin.json"
        scripts = plugin_root / "scripts"
        scripts.mkdir(parents=True)
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "project-workflow", "version": "0.4.0"}),
            encoding="utf-8",
        )
        (scripts / "workflow_state.py").write_text(
            'print("init approve check-execute transition start-execution complete validate")\n',
            encoding="utf-8",
        )
        (scripts / "orchestration_state.py").write_text(
            'print("init validate ready assign activate complete release block")\n',
            encoding="utf-8",
        )

        result = self.run_doctor(
            "--plugin-root",
            str(plugin_root),
            "--json",
            include_plugin_root=False,
            expected=2,
        )
        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["cli"]["workflow_state"])
        self.assertIn(
            "WORKFLOW_CLI_INVALID",
            {item["code"] for item in payload["issues"]},
        )
        workflow_issue = next(
            item for item in payload["issues"] if item["code"] == "WORKFLOW_CLI_INVALID"
        )
        self.assertIn("resume", workflow_issue["message"])

    def test_untrusted_plugin_root_is_never_executed(self) -> None:
        """An inspected repository must not supply executable Doctor helpers."""
        plugin_root = self.repo / "plugins/project-workflow"
        scripts = plugin_root / "scripts"
        manifest = plugin_root / ".codex-plugin/plugin.json"
        scripts.mkdir(parents=True)
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "project-workflow", "version": "0.4.0"}),
            encoding="utf-8",
        )
        marker = self.repo / "untrusted-script-ran"
        payload = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
            "print('init approve check-execute transition start-execution complete "
            "validate experience ready assign activate release block')\n"
        )
        (scripts / "workflow_state.py").write_text(payload, encoding="utf-8")
        (scripts / "orchestration_state.py").write_text(payload, encoding="utf-8")

        default_result = self.run_doctor("--json", include_plugin_root=False)
        default_output = json.loads(default_result.stdout)
        self.assertEqual(str(PLUGIN_ROOT), default_output["plugin"]["root"])
        self.assertFalse(marker.exists())

        result = self.run_doctor(
            "--plugin-root",
            str(plugin_root),
            "--json",
            include_plugin_root=False,
            expected=2,
        )

        self.assertFalse(marker.exists())
        output = json.loads(result.stdout)
        self.assertIn("PLUGIN_ROOT_UNTRUSTED", {item["code"] for item in output["issues"]})

    def test_text_output_is_one_summary_line(self) -> None:
        result = self.run_doctor()
        self.assertEqual(1, len(result.stdout.splitlines()))
        self.assertIn("Project Workflow doctor: OK", result.stdout)
        self.assertIn("native agents UNKNOWN", result.stdout)

    def test_stale_plugin_hint_is_quietly_recovered(self) -> None:
        stale = self.repo / "missing-cache-version"
        result = self.run_doctor(
            "--plugin-root",
            str(stale),
            "--json",
            include_plugin_root=False,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["plugin"]["recovered"])
        self.assertEqual(str(PLUGIN_ROOT), payload["plugin"]["root"])
        self.assertNotIn(str(stale), result.stdout)

    def test_state_directory_file_is_blocking(self) -> None:
        state_parent = self.repo / ".codex"
        state_parent.mkdir()
        (state_parent / "project-workflow").write_text("not a directory", encoding="utf-8")
        result = self.run_doctor("--json", expected=2)
        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["status"])
        self.assertFalse(payload["repository"]["state_writable"])
        self.assertIn(
            "STATE_DIRECTORY_NOT_WRITABLE",
            {item["code"] for item in payload["issues"]},
        )

    def test_state_directory_symlink_escape_is_blocking(self) -> None:
        """State evidence must not be written through a repository symlink."""
        external = Path(self.temporary_directory.name) / "external"
        external.mkdir()
        state_parent = self.repo / ".codex"
        state_parent.mkdir()
        (state_parent / "project-workflow").symlink_to(external, target_is_directory=True)

        result = self.run_doctor("--json", expected=2)

        payload = json.loads(result.stdout)
        self.assertFalse(payload["repository"]["state_writable"])
        self.assertIn(
            "STATE_DIRECTORY_UNSAFE",
            {item["code"] for item in payload["issues"]},
        )

    def test_state_parent_symlink_escape_is_blocking(self) -> None:
        """The state root parent must also be a real repository directory."""
        external = Path(self.temporary_directory.name) / "external-parent"
        external.mkdir()
        (self.repo / ".codex").symlink_to(external, target_is_directory=True)

        result = self.run_doctor("--json", expected=2)

        payload = json.loads(result.stdout)
        self.assertFalse(payload["repository"]["state_writable"])
        self.assertIn(
            "STATE_DIRECTORY_UNSAFE",
            {item["code"] for item in payload["issues"]},
        )

    def test_unwritable_state_directory_is_blocking(self) -> None:
        state_directory = self.repo / ".codex/project-workflow"
        state_directory.mkdir(parents=True)
        state_directory.chmod(0o500)
        self.addCleanup(state_directory.chmod, 0o700)
        if os.access(state_directory, os.W_OK):
            self.skipTest("current user can write through restrictive directory permissions")
        result = self.run_doctor("--json", expected=2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["repository"]["state_writable"])
        self.assertIn(
            "STATE_DIRECTORY_NOT_WRITABLE",
            {item["code"] for item in payload["issues"]},
        )

    def test_plan_and_matching_orchestration_revision_are_accepted(self) -> None:
        plan = self.initialize_plan()
        state = self.repo / ".codex/project-workflow/doctor-test/orchestration.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps(self.valid_orchestration()), encoding="utf-8")
        result = self.run_doctor(
            "--plan",
            str(plan.relative_to(self.repo)),
            "--orchestration",
            str(state.relative_to(self.repo)),
            "--json",
        )
        payload = json.loads(result.stdout)
        self.assertEqual("OK", payload["plan"]["status"])
        self.assertEqual("OK", payload["plan"]["orchestration_status"])
        self.assertEqual(1, payload["plan"]["revision"])

    def test_revision_mismatch_is_blocking(self) -> None:
        plan = self.initialize_plan()
        state = self.repo / "orchestration.json"
        orchestration = self.valid_orchestration()
        orchestration["revision"] = 2
        state.write_text(json.dumps(orchestration), encoding="utf-8")
        result = self.run_doctor(
            "--plan",
            str(plan),
            "--orchestration",
            str(state),
            "--json",
            expected=2,
        )
        payload = json.loads(result.stdout)
        self.assertEqual("BLOCKED", payload["plan"]["orchestration_status"])
        self.assertIn(
            "ORCHESTRATION_INCOMPATIBLE",
            {item["code"] for item in payload["issues"]},
        )

    def test_completed_plan_requires_complete_bound_orchestration(self) -> None:
        """Reuse the exact final validator and require the accepted state version."""
        plan = self.initialize_plan()
        state_path = self.repo / ".codex/project-workflow/doctor-test/orchestration.json"
        state_path.parent.mkdir(parents=True)
        state = self.completed_orchestration()
        state["tasks"][0]["status"] = "ASSIGNED"
        state["tasks"][0]["evidence"] = []
        self.mark_plan_completed(plan)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        content = plan.read_text(encoding="utf-8").replace(
            "---\n\n# Test plan",
            'orchestration_state: ".codex/project-workflow/doctor-test/orchestration.json"\n'
            "---\n\n# Test plan",
        )
        plan.write_text(content, encoding="utf-8")

        incomplete = self.run_doctor("--plan", str(plan), "--json", expected=2)
        payload = json.loads(incomplete.stdout)
        self.assertIn(
            "FINAL_EVIDENCE_INVALID",
            {item["code"] for item in payload["issues"]},
        )

        state = self.completed_orchestration()
        state_path.write_text(json.dumps(state), encoding="utf-8")
        accepted = self.run_doctor("--plan", str(plan), "--json")
        self.assertEqual("OK", json.loads(accepted.stdout)["plan"]["orchestration_status"])

        plan.write_text(
            plan.read_text(encoding="utf-8").replace(
                "final_orchestration_state_version: 4",
                "final_orchestration_state_version: 3",
            ),
            encoding="utf-8",
        )
        mismatch = self.run_doctor("--plan", str(plan), "--json", expected=2)
        self.assertIn(
            "FINAL_EVIDENCE_INVALID",
            {item["code"] for item in json.loads(mismatch.stdout)["issues"]},
        )

    def test_completed_none_plan_requires_persisted_final_evidence(self) -> None:
        """Doctor must reject missing or tampered immutable NONE evidence."""
        plan = self.complete_none_plan()
        accepted = self.run_doctor("--plan", str(plan), "--json")
        self.assertEqual("OK", json.loads(accepted.stdout)["plan"]["status"])

        baseline = self.repo / ".codex/project-workflow/doctor-test/filesystem-baseline.json"
        baseline.unlink()
        missing = self.run_doctor("--plan", str(plan), "--json", expected=2)
        self.assertIn(
            "FINAL_EVIDENCE_INVALID",
            {item["code"] for item in json.loads(missing.stdout)["issues"]},
        )

    def test_completed_none_plan_rejects_tampered_final_digest(self) -> None:
        """Doctor must bind the final artifact digest and reported counts."""
        plan = self.complete_none_plan()
        content = plan.read_text(encoding="utf-8").replace(
            "final_filesystem_artifact_sha256: \"",
            "final_filesystem_artifact_sha256: \"0",
            1,
        )
        plan.write_text(content, encoding="utf-8")
        result = self.run_doctor("--plan", str(plan), "--json", expected=2)
        self.assertIn(
            "FINAL_EVIDENCE_INVALID",
            {item["code"] for item in json.loads(result.stdout)["issues"]},
        )

    def test_repository_relative_inputs_cannot_escape(self) -> None:
        """Reject parent traversal and absolute paths outside the inspected repository."""
        outside_plan = Path(self.temporary_directory.name) / "outside.md"
        outside_plan.write_text("# Outside\n", encoding="utf-8")
        plan_result = self.run_doctor(
            "--plan", "../outside.md", "--json", expected=2
        )
        self.assertIn("PLAN_INVALID", {item["code"] for item in json.loads(plan_result.stdout)["issues"]})

        plan = self.initialize_plan()
        outside_state = Path(self.temporary_directory.name) / "outside.json"
        outside_state.write_text(json.dumps(self.valid_orchestration()), encoding="utf-8")
        state_result = self.run_doctor(
            "--plan",
            str(plan),
            "--orchestration",
            str(outside_state),
            "--json",
            expected=2,
        )
        self.assertIn(
            "ORCHESTRATION_INCOMPATIBLE",
            {item["code"] for item in json.loads(state_result.stdout)["issues"]},
        )

    def test_orchestration_without_plan_is_blocking(self) -> None:
        result = self.run_doctor(
            "--orchestration",
            "orchestration.json",
            "--json",
            expected=2,
        )
        payload = json.loads(result.stdout)
        self.assertIn("STATE_WITHOUT_PLAN", {item["code"] for item in payload["issues"]})

    def test_invalid_orchestration_contracts_are_blocking(self) -> None:
        """Doctor must reuse the scheduler's complete structural validation."""
        plan = self.initialize_plan()
        mutations = {}

        malformed = self.valid_orchestration()
        malformed["tasks"] = "forged"
        mutations["malformed tasks"] = malformed

        cycle = self.valid_orchestration()
        cycle["tasks"].append(
            {
                **cycle["tasks"][0],
                "id": "T02",
                "write_scope": ["tests"],
                "depends_on": ["T01"],
            }
        )
        cycle["tasks"][0]["depends_on"] = ["T02"]
        mutations["dependency cycle"] = cycle

        overlap = self.valid_orchestration()
        overlap["max_workers"] = 2
        overlap["tasks"] = [
            {
                **overlap["tasks"][0],
                "status": "ASSIGNED",
                "owner": "coordinator-a",
                "started_at": "2026-08-25T00:00:00+00:00",
                "assignment_kind": "COORDINATOR",
            },
            {
                **overlap["tasks"][0],
                "id": "T02",
                "status": "ASSIGNED",
                "owner": "coordinator-b",
                "started_at": "2026-08-25T00:00:00+00:00",
                "assignment_kind": "COORDINATOR",
            },
        ]
        mutations["overlapping active scopes"] = overlap

        forged = self.valid_orchestration()
        forged["tasks"][0].update(
            {
                "status": "ASSIGNED",
                "owner": "fake-worker",
                "started_at": "2026-08-25T00:00:00+00:00",
                "assignment_kind": "WORKER",
                "spawn_status": "RUNNING",
                "runtime_verification": "VERIFIED",
            }
        )
        mutations["forged worker"] = forged

        for label, orchestration in mutations.items():
            with self.subTest(label=label):
                state = self.repo / f"{label.replace(' ', '-')}.json"
                state.write_text(json.dumps(orchestration), encoding="utf-8")
                result = self.run_doctor(
                    "--plan",
                    str(plan),
                    "--orchestration",
                    str(state),
                    "--json",
                    expected=2,
                )
                payload = json.loads(result.stdout)
                self.assertEqual("BLOCKED", payload["plan"]["orchestration_status"])
                self.assertIn(
                    "ORCHESTRATION_INCOMPATIBLE",
                    {item["code"] for item in payload["issues"]},
                )


if __name__ == "__main__":
    unittest.main()
