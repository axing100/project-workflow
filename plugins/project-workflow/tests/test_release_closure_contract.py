"""Independent release-closure contract tests for Project Workflow v0.4."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts"
WORKFLOW_STATE = SCRIPT_ROOT / "workflow_state.py"
FILESYSTEM_SNAPSHOT = SCRIPT_ROOT / "filesystem_snapshot.py"
ORCHESTRATION_STATE = SCRIPT_ROOT / "orchestration_state.py"
DOCTOR = SCRIPT_ROOT / "project_workflow_doctor.py"

sys.path.insert(0, str(SCRIPT_ROOT))
import filesystem_snapshot as snapshot_module

ORCHESTRATION_SPEC = importlib.util.spec_from_file_location(
    "release_closure_orchestration_state",
    ORCHESTRATION_STATE,
)
assert ORCHESTRATION_SPEC is not None and ORCHESTRATION_SPEC.loader is not None
orchestration_module = importlib.util.module_from_spec(ORCHESTRATION_SPEC)
ORCHESTRATION_SPEC.loader.exec_module(orchestration_module)


class ReleaseClosureContractTest(unittest.TestCase):
    """Verify the public release-closure contract from fresh repositories."""

    approval = "I approve release-closure revision 1."
    approved_at = "2026-08-25T00:00:00+00:00"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()
        self.plan = self.repo / "docs/plan/release.md"

    def run_cli(
        self,
        script: Path,
        *arguments: object,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        """Run one helper as an external process and assert its exit code."""
        result = subprocess.run(
            [sys.executable, str(script), *(str(argument) for argument in arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return result

    def workflow(self, *arguments: object, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the workflow lifecycle helper."""
        return self.run_cli(WORKFLOW_STATE, *arguments, expected=expected)

    def snapshot(self, *arguments: object, expected: int = 0) -> subprocess.CompletedProcess[str]:
        """Run the filesystem evidence helper."""
        return self.run_cli(FILESYSTEM_SNAPSHOT, *arguments, expected=expected)

    def orchestration(
        self,
        *arguments: object,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        """Run the orchestration helper."""
        return self.run_cli(ORCHESTRATION_STATE, *arguments, expected=expected)

    def doctor(self, plan: Path, repo: Path | None = None, expected: int = 0) -> dict[str, object]:
        """Run Doctor and return its stable JSON payload."""
        inspected_repo = repo or self.repo
        result = self.run_cli(
            DOCTOR,
            "--repo",
            inspected_repo,
            "--plugin-root",
            PLUGIN_ROOT,
            "--plan",
            plan,
            "--json",
            expected=expected,
        )
        return json.loads(result.stdout)

    def initialize_plan(self, plan_id: str = "release-closure") -> None:
        """Create a current VCS NONE plan at the confirmation boundary."""
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text("# Release Closure\n\nIndependent contract fixture.\n", encoding="utf-8")
        self.workflow(
            "init",
            self.plan,
            "--plan-id",
            plan_id,
            "--repo",
            self.repo,
            "--vcs-mode",
            "NONE",
        )

    def add_frontmatter(self, *lines: str, plan: Path | None = None) -> None:
        """Insert additional constrained frontmatter before the Markdown body."""
        target = plan or self.plan
        text = target.read_text(encoding="utf-8")
        marker = "---\n\n# Release Closure"
        self.assertIn(marker, text)
        target.write_text(
            text.replace(marker, "".join(f"{line}\n" for line in lines) + marker, 1),
            encoding="utf-8",
        )

    def configure_standard_none(self, *, with_orchestration: bool = False) -> None:
        """Add current STANDARD/NONE evidence fields to the generated plan."""
        lines = [
            'workflow_profile: "STANDARD"',
            'rollback_required: "false"',
            'filesystem_snapshot_scopes: []',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["docs/plan","src"]',
        ]
        if with_orchestration:
            lines.extend(
                [
                    'execution_mode: "SINGLE_AGENT"',
                    "max_workers: 1",
                    'agent_topology: "SHARED_WORKSPACE"',
                    'orchestration_state: ".codex/project-workflow/release-closure/orchestration.json"',
                ]
            )
        self.add_frontmatter(*lines)

    def inspect_plan(self, plan: Path | None = None) -> dict[str, object]:
        """Return normalized plan metadata."""
        result = self.workflow("inspect", plan or self.plan)
        return json.loads(result.stdout)

    def write_completed_orchestration(self, repo: Path | None = None, version: int = 9) -> Path:
        """Persist one complete coordinator task for the lifecycle final gate."""
        root = repo or self.repo
        state = root / ".codex/project-workflow/release-closure/orchestration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps(
                {
                    "schema": "project-workflow/orchestration/v1",
                    "plan_id": "release-closure",
                    "revision": 1,
                    "execution_mode": "SINGLE_AGENT",
                    "max_workers": 1,
                    "topology": "SHARED_WORKSPACE",
                    "policy_contract": "v0.4",
                    "state_version": version,
                    "tasks": [
                        {
                            "id": "T01",
                            "display_name": "Coordinator check",
                            "status": "COMPLETED",
                            "depends_on": [],
                            "write_scope": ["docs/plan", "src"],
                            "agent_eligible": False,
                            "owner": "coordinator",
                            "started_at": "2026-08-25T00:00:01+00:00",
                            "attempts": 1,
                            "evidence": ["verified"],
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
                    ],
                    "events": [],
                }
            ),
            encoding="utf-8",
        )
        return state

    def complete_current_none_plan(self) -> Path:
        """Create one completed current NONE plan with bound immutable evidence."""
        self.initialize_plan()
        self.configure_standard_none(with_orchestration=True)
        (self.repo / "src").mkdir()
        (self.repo / "src/service.txt").write_text("before\n", encoding="utf-8")
        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        (self.repo / "src/service.txt").write_text("after\n", encoding="utf-8")
        self.write_completed_orchestration()
        self.workflow("complete", self.plan, "--repo", self.repo)
        self.workflow("validate", self.plan, "--repo", self.repo)
        self.assertEqual("OK", self.doctor(self.plan)["status"])
        return self.plan

    def default_task(self) -> dict[str, object]:
        """Return a minimally complete pending task record."""
        return {
            "id": "T01",
            "display_name": "Implementation",
            "status": "PENDING",
            "depends_on": [],
            "write_scope": ["src"],
            "agent_eligible": True,
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

    def orchestration_document(
        self,
        *,
        policy_contract: str | None = "v0.4",
        task: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Return one scheduler document for Worker identity checks."""
        document: dict[str, object] = {
            "schema": "project-workflow/orchestration/v1",
            "plan_id": "release-closure",
            "revision": 1,
            "execution_mode": "AUTO_MULTI_AGENT",
            "max_workers": 1,
            "topology": "SHARED_WORKSPACE",
            "tasks": [task or self.default_task()],
            "events": [],
        }
        if policy_contract is not None:
            document["policy_contract"] = policy_contract
            document["state_version"] = 3
        return document

    def test_current_standard_none_without_baseline_cannot_complete(self) -> None:
        """A current STANDARD/NONE plan cannot complete without bound baseline evidence."""
        self.initialize_plan()
        self.configure_standard_none()
        self.workflow(
            "approve",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        text = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            text.replace('phase: "APPROVED"', 'phase: "IN_PROGRESS"', 1),
            encoding="utf-8",
        )
        before = self.plan.read_bytes()

        result = self.workflow("complete", self.plan, "--repo", self.repo, expected=2)

        self.assertIn("current NONE plan requires a bound filesystem baseline", result.stderr)
        self.assertEqual(before, self.plan.read_bytes())

    def test_canonical_start_approves_binds_baseline_and_is_idempotent(self) -> None:
        """One start-execution confirmation atomically approves, binds, and starts NONE work."""
        self.initialize_plan()
        self.configure_standard_none()
        (self.repo / "src").mkdir()
        (self.repo / "src/service.txt").write_text("before\n", encoding="utf-8")

        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        metadata = self.inspect_plan()
        self.assertEqual("IN_PROGRESS", metadata["phase"])
        self.assertEqual(1, metadata["approved_revision"])
        self.assertEqual(self.approved_at, metadata["approved_at"])
        self.assertEqual(self.approval, metadata["confirmation_record"])
        self.assertIn("approved_filesystem_policy_sha256", metadata)
        baseline_path = self.repo / str(metadata["filesystem_baseline"])
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.assertEqual("v0.4", baseline["binding"]["policy_contract"])
        self.assertEqual("release-closure", baseline["binding"]["plan_id"])
        self.assertEqual(1, baseline["binding"]["revision"])
        self.assertEqual(1, baseline["binding"]["approved_revision"])
        self.assertEqual(
            hashlib.sha256(self.approval.encode("utf-8")).hexdigest(),
            baseline["binding"]["confirmation_sha256"],
        )
        self.assertEqual(
            snapshot_module.canonical_json_sha256(baseline),
            metadata["filesystem_baseline_sha256"],
        )

        before_retry = self.plan.read_bytes()
        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        self.assertEqual(before_retry, self.plan.read_bytes())

    def test_conflicting_baseline_blocks_start_without_partial_approval(self) -> None:
        """A stale baseline conflict is atomic, and retry succeeds after removing it."""
        self.initialize_plan()
        self.configure_standard_none()
        (self.repo / "src").mkdir()
        (self.repo / "src/service.txt").write_text("before\n", encoding="utf-8")
        baseline = self.repo / ".codex/project-workflow/release-closure/filesystem-baseline.json"
        self.snapshot(
            "create",
            "--repo",
            self.repo,
            "--output",
            ".codex/project-workflow/release-closure/filesystem-baseline.json",
        )
        original_plan = self.plan.read_bytes()
        original_baseline = baseline.read_bytes()

        result = self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
            expected=2,
        )
        self.assertIn("filesystem baseline already exists", result.stderr)
        self.assertEqual(original_plan, self.plan.read_bytes())
        self.assertEqual(original_baseline, baseline.read_bytes())

        baseline.unlink()
        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        self.assertEqual("IN_PROGRESS", self.inspect_plan()["phase"])

    def test_filesystem_baseline_create_requires_digest_cas_for_replacement(self) -> None:
        """Public baseline creation refuses overwrite unless the old digest matches."""
        (self.repo / "src").mkdir()
        (self.repo / "src/service.txt").write_text("before\n", encoding="utf-8")
        output = ".codex/project-workflow/cas/filesystem-baseline.json"
        created = self.snapshot(
            "create",
            "--repo",
            self.repo,
            "--output",
            output,
        )
        summary = json.loads(created.stdout)
        self.assertEqual(64, len(summary["sha256"]))
        baseline_path = self.repo / output
        original = baseline_path.read_bytes()
        self.assertEqual(
            summary["sha256"],
            snapshot_module.canonical_json_sha256(
                json.loads(baseline_path.read_text(encoding="utf-8"))
            ),
        )
        (self.repo / "src/service.txt").write_text("after\n", encoding="utf-8")

        repeated = self.snapshot(
            "create",
            "--repo",
            self.repo,
            "--output",
            output,
            expected=2,
        )
        self.assertIn("already exists", repeated.stderr)
        self.assertEqual(original, baseline_path.read_bytes())

        stale = self.snapshot(
            "create",
            "--repo",
            self.repo,
            "--output",
            output,
            "--replace-if-sha256",
            "0" * 64,
            expected=2,
        )
        self.assertIn("digest conflict", stale.stderr)
        self.assertEqual(original, baseline_path.read_bytes())

        self.snapshot(
            "create",
            "--repo",
            self.repo,
            "--output",
            output,
            "--replace-if-sha256",
            summary["sha256"],
        )
        self.assertNotEqual(original, baseline_path.read_bytes())

    def test_v04_completed_worker_requires_runtime_identity_and_legacy_is_readable(self) -> None:
        """v0.4 completed Workers need full runtime proof; pure legacy remains readable."""
        self.initialize_plan()
        self.configure_standard_none()
        self.add_frontmatter(
            'execution_mode: "AUTO_MULTI_AGENT"',
            "max_workers: 1",
            'agent_topology: "SHARED_WORKSPACE"',
        )
        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        state = self.repo / ".codex/project-workflow/release-closure/orchestration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        task = self.default_task()
        task.update(
            {
                "status": "COMPLETED",
                "owner": "worker-a",
                "started_at": "2026-08-25T00:00:00+00:00",
                "attempts": 1,
                "evidence": ["accepted"],
                "assignment_kind": "WORKER",
            }
        )
        state.write_text(
            json.dumps(self.orchestration_document(policy_contract="v0.4", task=task)),
            encoding="utf-8",
        )
        missing_identity = self.orchestration(
            "validate",
            state,
            "--plan",
            self.plan,
            "--repo",
            self.repo,
            "--final",
            expected=2,
        )
        self.assertIn("completed worker task T01", missing_identity.stderr)

        task.update(
            {
                "runtime_agent_id": "agent-t01",
                "runtime_task_name": "/root/worker-a",
                "spawn_status": "COMPLETED",
                "spawned_at": "2026-08-25T00:00:01+00:00",
                "finished_at": "2026-08-25T00:00:02+00:00",
                "runtime_verification": "UNAVAILABLE",
            }
        )
        state.write_text(
            json.dumps(self.orchestration_document(policy_contract="v0.4", task=task)),
            encoding="utf-8",
        )
        unverified = self.orchestration(
            "validate",
            state,
            "--plan",
            self.plan,
            "--repo",
            self.repo,
            "--final",
            expected=2,
        )
        self.assertIn("requires VERIFIED runtime", unverified.stderr)

        task["runtime_verification"] = "VERIFIED"
        state.write_text(
            json.dumps(self.orchestration_document(policy_contract="v0.4", task=task)),
            encoding="utf-8",
        )
        self.orchestration("validate", state, "--plan", self.plan, "--repo", self.repo, "--final")

        legacy_state = self.repo / ".codex/project-workflow/legacy/orchestration.json"
        legacy_state.parent.mkdir(parents=True)
        legacy_task = self.default_task()
        legacy_task.update(
            {
                "status": "COMPLETED",
                "owner": "legacy-worker",
                "started_at": "2026-08-20T00:00:00+00:00",
                "attempts": 1,
                "evidence": ["historical evidence"],
                "assignment_kind": "WORKER",
            }
        )
        legacy_state.write_text(
            json.dumps(self.orchestration_document(policy_contract=None, task=legacy_task)),
            encoding="utf-8",
        )
        inspected = self.orchestration("inspect", legacy_state)
        normalized = json.loads(inspected.stdout)
        self.assertEqual("legacy", normalized["policy_contract"])
        self.assertEqual("UNAVAILABLE", normalized["tasks"][0]["runtime_verification"])

    def test_completed_none_evidence_tampering_blocks_validate_and_doctor(self) -> None:
        """Completed NONE evidence deletion or tampering is rejected by both gates."""
        self.complete_current_none_plan()
        fixture_root = Path(self.temporary_directory.name) / "completed-fixture"
        shutil.copytree(self.repo, fixture_root)
        baseline_rel = self.inspect_plan()["filesystem_baseline"]
        artifact_rel = self.inspect_plan()["final_filesystem_artifact"]

        def assert_blocked(copy_name: str, mutate: object, expected_text: str) -> None:
            target_repo = Path(self.temporary_directory.name) / copy_name
            shutil.copytree(fixture_root, target_repo)
            target_plan = target_repo / "docs/plan/release.md"
            mutate(target_repo, target_plan)
            validation = self.workflow(
                "validate",
                target_plan,
                "--repo",
                target_repo,
                expected=2,
            )
            self.assertIn(expected_text, validation.stderr)
            doctor_payload = self.doctor(target_plan, repo=target_repo, expected=2)
            self.assertEqual("BLOCKED", doctor_payload["status"])
            self.assertIn(
                "FINAL_EVIDENCE_INVALID",
                {item["code"] for item in doctor_payload["issues"]},
            )

        def delete_baseline(repo: Path, _plan: Path) -> None:
            (repo / str(baseline_rel)).unlink()

        def delete_artifact(repo: Path, _plan: Path) -> None:
            (repo / str(artifact_rel)).unlink()

        def tamper_artifact_digest(_repo: Path, plan: Path) -> None:
            plan.write_text(
                plan.read_text(encoding="utf-8").replace(
                    'final_filesystem_artifact_sha256: "',
                    'final_filesystem_artifact_sha256: "0',
                    1,
                ),
                encoding="utf-8",
            )

        def tamper_counts(_repo: Path, plan: Path) -> None:
            lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
            changed = False
            for index, line in enumerate(lines):
                if line.startswith("final_filesystem_modified_count: "):
                    current = int(line.split(":", 1)[1].strip())
                    replacement = 0 if current else 1
                    lines[index] = f"final_filesystem_modified_count: {replacement}\n"
                    changed = True
                    break
            self.assertTrue(changed)
            plan.write_text("".join(lines), encoding="utf-8")

        def tamper_state_version(repo: Path, _plan: Path) -> None:
            state = repo / ".codex/project-workflow/release-closure/orchestration.json"
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload["state_version"] += 1
            state.write_text(json.dumps(payload), encoding="utf-8")

        cases = (
            ("missing_baseline", delete_baseline, "cannot read filesystem JSON"),
            ("missing_artifact", delete_artifact, "invalid final filesystem artifact"),
            ("digest_mismatch", tamper_artifact_digest, "artifact digest"),
            ("count_mismatch", tamper_counts, "modified count"),
            ("state_version_mismatch", tamper_state_version, "state version"),
        )
        for name, mutation, expected_text in cases:
            with self.subTest(name=name):
                assert_blocked(name, mutation, expected_text)

    def test_orchestration_parent_swap_cannot_redirect_state_write(self) -> None:
        """A parent-directory swap to a symlink cannot write scheduler state outside."""
        self.initialize_plan()
        self.configure_standard_none()
        self.add_frontmatter(
            'execution_mode: "AUTO_MULTI_AGENT"',
            "max_workers: 1",
            'agent_topology: "SHARED_WORKSPACE"',
        )
        self.workflow(
            "start-execution",
            self.plan,
            "--repo",
            self.repo,
            "--confirmation",
            self.approval,
            "--at",
            self.approved_at,
        )
        state_root = self.repo / ".codex/project-workflow"
        state = state_root / "release-closure/orchestration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps(self.orchestration_document(policy_contract="v0.4")),
            encoding="utf-8",
        )
        moved_root = self.repo / "trusted-project-workflow"
        outside = self.repo / "outside-state"
        outside_state = outside / "release-closure/orchestration.json"
        outside_state.parent.mkdir(parents=True)
        original_outside = state.read_bytes()
        outside_state.write_bytes(original_outside)
        real_open = os.open
        swapped = False

        def swap_before_temp_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal swapped
            basename = os.path.basename(os.fspath(path))
            if (
                not swapped
                and basename.startswith(".orchestration.json.")
                and not basename.endswith(".lock")
            ):
                state_root.rename(moved_root)
                state_root.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        argv = [
            str(ORCHESTRATION_STATE),
            "block",
            str(state),
            "T01",
            "--reason",
            "parent swapped after lock",
            "--plan",
            str(self.plan),
            "--repo",
            str(self.repo),
        ]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            orchestration_module.os,
            "open",
            side_effect=swap_before_temp_open,
        ), redirect_stdout(output):
            self.assertEqual(0, orchestration_module.main())

        self.assertTrue(swapped)
        self.assertIn("blocked T01", output.getvalue())
        self.assertEqual(original_outside, outside_state.read_bytes())
        trusted = json.loads(
            (moved_root / "release-closure/orchestration.json").read_text(encoding="utf-8")
        )
        self.assertEqual("BLOCKED", trusted["tasks"][0]["status"])

    def test_pure_legacy_plan_remains_valid_without_v04_fields(self) -> None:
        """A plan without v0.4 marker or transition fields keeps legacy compatibility."""
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text(
            "---\n"
            'workflow: "project-workflow/v1"\n'
            'plan_id: "legacy-release"\n'
            "revision: 1\n"
            'phase: "AWAITING_CONFIRMATION"\n'
            "approved_revision: \n"
            "approved_at: \n"
            "confirmation_record: \n"
            "---\n\n"
            "# Release Closure\n\nLegacy fixture.\n",
            encoding="utf-8",
        )

        self.workflow("validate", self.plan, "--repo", self.repo)
        metadata = self.inspect_plan()
        self.assertNotIn("policy_contract", metadata)
        self.assertNotIn("workflow_profile", metadata)


if __name__ == "__main__":
    unittest.main()
