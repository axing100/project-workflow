"""Tests for the Project Workflow state helper."""

from __future__ import annotations

import json
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"
SNAPSHOT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "filesystem_snapshot.py"


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

    def start_execution(self, confirmation: str = "I approve test-plan revision 1.") -> None:
        """Start execution with a deterministic approval timestamp."""
        self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            confirmation,
            "--at",
            "2026-08-20T00:00:00+00:00",
        )

    def inspect(self) -> dict[str, object]:
        """Return inspected workflow metadata."""
        result = self.run_command("inspect", str(self.plan))
        return json.loads(result.stdout)

    def add_metadata(self, *lines: str) -> None:
        """Insert additional frontmatter fields before the plan body."""
        content = self.plan.read_text(encoding="utf-8")
        marker = "---\n\n# Implementation Plan"
        self.assertIn(marker, content)
        insertion = "".join(f"{line}\n" for line in lines)
        self.plan.write_text(content.replace(marker, insertion + marker, 1), encoding="utf-8")

    def write_orchestration_state(self, completed: bool) -> Path:
        """Write one valid coordinator task for lifecycle final-gate tests."""
        state = (
            Path(self.temporary_directory.name)
            / ".codex/project-workflow/test-plan/orchestration.json"
        )
        state.parent.mkdir(parents=True, exist_ok=True)
        status = "COMPLETED" if completed else "ASSIGNED"
        state.write_text(
            json.dumps(
                {
                    "schema": "project-workflow/orchestration/v1",
                    "plan_id": "test-plan",
                    "revision": 1,
                    "execution_mode": "SINGLE_AGENT",
                    "max_workers": 1,
                    "max_attempts": 2,
                    "topology": "SHARED_WORKSPACE",
                    "policy_contract": "v0.4",
                    "state_version": 7,
                    "tasks": [
                        {
                            "id": "T01",
                            "display_name": "Lifecycle check",
                            "status": status,
                            "depends_on": [],
                            "write_scope": ["module-a"],
                            "agent_eligible": False,
                            "owner": "coordinator",
                            "started_at": "2026-08-20T00:00:01+00:00",
                            "attempts": 1,
                            "evidence": ["verified"] if completed else [],
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

    def create_none_baseline(self, *scopes: str) -> None:
        """Create the documented internal baseline for a NONE completion test."""
        command = [
            sys.executable,
            str(SNAPSHOT_SCRIPT),
            "create",
            "--repo",
            self.temporary_directory.name,
            "--output",
            ".codex/project-workflow/test-plan/filesystem-baseline.json",
        ]
        for scope in scopes:
            command.extend(("--scope", scope))
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_init_preserves_markdown_body(self) -> None:
        self.initialize()
        metadata = self.inspect()
        self.assertEqual("v0.5", metadata["policy_contract"])
        self.assertEqual("AWAITING_CONFIRMATION", metadata["phase"])
        self.assertEqual(1, metadata["revision"])
        self.assertEqual("Implementation Plan", metadata["conversation_title"])
        self.assertEqual(5, metadata["progress_heartbeat_minutes"])
        self.assertIn("# Implementation Plan\n\nKeep this body.\n", self.plan.read_text(encoding="utf-8"))

    def test_plan_lock_does_not_pollute_document_directory(self) -> None:
        """Store lifecycle locks outside the user-facing plan directory."""
        self.initialize()

        self.assertFalse((self.plan.parent / f".{self.plan.name}.lock").exists())

    def test_explicit_repo_uses_internal_plan_lock(self) -> None:
        """Keep repository-scoped lifecycle locks under the internal state root."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--repo", str(repo)
        )

        locks = list((repo / ".codex/project-workflow/.locks").glob("plan-*.lock"))
        self.assertEqual(1, len(locks))
        self.assertFalse((self.plan.parent / f".{self.plan.name}.lock").exists())

    def test_explicit_repo_rejects_symlinked_internal_lock_parent(self) -> None:
        """Do not redirect lifecycle locks through a repository state symlink."""
        repo = Path(self.temporary_directory.name)
        external = repo.parent / f"{repo.name}-external-locks"
        external.mkdir()
        self.addCleanup(lambda: external.rmdir() if external.exists() else None)
        (repo / ".codex").symlink_to(external, target_is_directory=True)

        result = self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            str(repo),
            expected=2,
        )

        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual([], list(external.iterdir()))

    def test_cleanup_legacy_lock_is_explicit(self) -> None:
        """Remove only an inactive adjacent lock through the explicit migration command."""
        legacy_lock = self.plan.parent / f".{self.plan.name}.lock"
        legacy_lock.touch()

        self.run_command("cleanup-legacy-lock", str(self.plan))

        self.assertFalse(legacy_lock.exists())
        self.assertFalse(any(self.plan.parent.glob(".*.md.lock")))

    def test_unknown_policy_contract_fails_closed(self) -> None:
        """A future or mistyped contract must not silently inherit legacy rules."""
        self.initialize()
        self.plan.write_text(
            self.plan.read_text(encoding="utf-8").replace(
                'policy_contract: "v0.5"', 'policy_contract: "v9"'
            ),
            encoding="utf-8",
        )
        result = self.run_command("validate", str(self.plan), expected=2)
        self.assertIn("unsupported policy_contract", result.stderr)

    def test_experience_reports_persisted_title_and_heartbeat(self) -> None:
        """Expose stable values for native title sync and bounded progress waits."""
        self.initialize()
        experience = json.loads(
            self.run_command("experience", str(self.plan)).stdout
        )
        self.assertEqual(
            {
                "conversation_title": "Implementation Plan",
                "progress_heartbeat_minutes": 5,
            },
            experience,
        )

    def test_experience_derives_legacy_plan_defaults(self) -> None:
        """Historical plans remain usable without new presentation metadata."""
        self.initialize()
        content = self.plan.read_text(encoding="utf-8")
        content = "\n".join(
            line
            for line in content.splitlines()
            if not line.startswith("conversation_title:")
            and not line.startswith("progress_heartbeat_minutes:")
        ) + "\n"
        self.plan.write_text(content, encoding="utf-8")

        experience = json.loads(
            self.run_command("experience", str(self.plan)).stdout
        )
        self.assertEqual("Implementation Plan", experience["conversation_title"])
        self.assertEqual(5, experience["progress_heartbeat_minutes"])

    def test_invalid_heartbeat_is_rejected_without_mutation(self) -> None:
        """Reject intervals that would disable or flood user-visible progress."""
        self.initialize()
        for invalid in (0, 61, "true"):
            with self.subTest(invalid=invalid):
                content = self.plan.read_text(encoding="utf-8")
                content = content.replace(
                    "progress_heartbeat_minutes: 5",
                    f"progress_heartbeat_minutes: {invalid}",
                    1,
                )
                self.plan.write_text(content, encoding="utf-8")
                before = self.plan.read_bytes()
                result = self.run_command(
                    "experience",
                    str(self.plan),
                    expected=2,
                )
                self.assertIn("between 1 and 60", result.stderr)
                self.assertEqual(before, self.plan.read_bytes())
                self.plan.write_text(
                    content.replace(
                        f"progress_heartbeat_minutes: {invalid}",
                        "progress_heartbeat_minutes: 5",
                        1,
                    ),
                    encoding="utf-8",
                )

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
        self.run_command("complete", str(self.plan))
        self.assertEqual("COMPLETED", self.inspect()["phase"])

    def test_start_execution_atomically_records_approval(self) -> None:
        self.initialize()
        self.start_execution()
        metadata = self.inspect()
        self.assertEqual("IN_PROGRESS", metadata["phase"])
        self.assertEqual(1, metadata["approved_revision"])
        self.assertEqual("2026-08-20T00:00:00+00:00", metadata["approved_at"])
        self.assertEqual("I approve test-plan revision 1.", metadata["confirmation_record"])
        self.assertIn("Keep this body.", self.plan.read_text(encoding="utf-8"))

    def test_start_execution_validation_failure_does_not_partially_update(self) -> None:
        self.initialize()
        original = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "   ",
            expected=2,
        )
        self.assertIn("confirmation must contain", result.stderr)
        self.assertEqual(original, self.plan.read_bytes())

        content = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            content.replace("approved_revision: \n", "approved_revision: 1\n", 1),
            encoding="utf-8",
        )
        stale = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            expected=2,
        )
        self.assertIn("must not retain an approval record", result.stderr)
        self.assertEqual(stale, self.plan.read_bytes())

    def test_start_execution_rejects_invalid_or_naive_time_without_update(self) -> None:
        self.initialize()
        original = self.plan.read_bytes()
        approval_times = (
            "not-a-time",
            "2026-08-20T00:00:00",
            "",
            "2026-08-20T00:00:00+24:00",
        )
        for approval_time in approval_times:
            with self.subTest(approval_time=approval_time):
                result = self.run_command(
                    "start-execution",
                    str(self.plan),
                    "--confirmation",
                    "I approve test-plan revision 1.",
                    "--at",
                    approval_time,
                    expected=2,
                )
                self.assertIn("approval time", result.stderr)
                self.assertEqual(original, self.plan.read_bytes())

    def test_start_execution_accepts_utc_z_time(self) -> None:
        self.initialize()
        self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            "--at",
            "2026-08-20T00:00:00Z",
        )
        self.assertEqual("2026-08-20T00:00:00Z", self.inspect()["approved_at"])

    def test_start_execution_supports_legacy_approved_plan(self) -> None:
        self.initialize()
        self.approve()
        self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
        )
        self.assertEqual("IN_PROGRESS", self.inspect()["phase"])

    def test_start_execution_is_idempotent_for_same_confirmation(self) -> None:
        self.initialize()
        self.start_execution()
        original = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            "--at",
            "2026-08-20T00:00:00+00:00",
        )
        self.assertIn("execution active", result.stdout)
        self.assertEqual(original, self.plan.read_bytes())

    def test_resume_is_idempotent_for_in_progress_plan(self) -> None:
        """Replay all execution gates without rewriting an active plan."""
        self.initialize()
        self.start_execution()
        original = self.plan.read_bytes()
        result = self.run_command("resume", str(self.plan))
        self.assertIn("execution active", result.stdout)
        self.assertEqual(original, self.plan.read_bytes())

    def test_persisted_approval_fields_require_exact_types_and_timezone(self) -> None:
        """Reject numeric or naive historical approval values without coercion."""
        self.initialize()
        self.start_execution()
        valid = self.plan.read_text(encoding="utf-8")
        replacements = (
            ('approved_at: "2026-08-20T00:00:00+00:00"', "approved_at: 123"),
            (
                'approved_at: "2026-08-20T00:00:00+00:00"',
                'approved_at: "2026-08-20T00:00:00"',
            ),
            (
                'confirmation_record: "I approve test-plan revision 1."',
                "confirmation_record: 123",
            ),
            (
                'confirmation_record: "I approve test-plan revision 1."',
                'confirmation_record: ["confirm"]',
            ),
            (
                'confirmation_record: "I approve test-plan revision 1."',
                'confirmation_record: {"confirmation": "confirm"}',
            ),
        )
        for original, replacement in replacements:
            with self.subTest(replacement=replacement):
                self.plan.write_text(valid.replace(original, replacement), encoding="utf-8")
                before = self.plan.read_bytes()
                result = self.run_command("validate", str(self.plan), expected=2)
                self.assertTrue(
                    "approved_at" in result.stderr or "confirmation_record" in result.stderr
                )
                self.assertEqual(before, self.plan.read_bytes())

    def test_plan_writes_preserve_existing_mode(self) -> None:
        """Keep the user's Markdown permissions across atomic replacement."""
        os.chmod(self.plan, 0o644)
        self.initialize()
        self.assertEqual(0o644, os.stat(self.plan).st_mode & 0o777)
        self.start_execution()
        self.assertEqual(0o644, os.stat(self.plan).st_mode & 0o777)

    def test_stale_plan_digest_rejects_mutation(self) -> None:
        """Expose an optional content CAS for lifecycle callers."""
        self.initialize()
        stale = "0" * 64
        before = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            "--expected-revision",
            "1",
            "--expected-phase",
            "AWAITING_CONFIRMATION",
            "--expected-sha256",
            stale,
            expected=2,
        )
        self.assertIn("plan content conflict", result.stderr)
        self.assertEqual(before, self.plan.read_bytes())

        digest = hashlib.sha256(before).hexdigest()
        self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            "--expected-revision",
            "1",
            "--expected-phase",
            "AWAITING_CONFIRMATION",
            "--expected-digest",
            digest,
        )

    def test_concurrent_conflicting_confirmations_have_one_winner(self) -> None:
        """Serialize complete approval read-modify-write operations."""
        self.initialize()
        commands = []
        for confirmation in ("first explicit approval", "second explicit approval"):
            commands.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start-execution",
                        str(self.plan),
                        "--confirmation",
                        confirmation,
                        "--at",
                        "2026-08-20T00:00:00+00:00",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        results = [process.communicate() + (process.returncode,) for process in commands]
        self.assertEqual([0, 2], sorted(result[2] for result in results))
        self.assertIn(self.inspect()["confirmation_record"], {
            "first explicit approval",
            "second explicit approval",
        })

    def test_start_execution_rejects_different_confirmation_without_update(self) -> None:
        self.initialize()
        self.start_execution()
        original = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "a different message",
            expected=2,
        )
        self.assertIn("does not match", result.stderr)
        self.assertEqual(original, self.plan.read_bytes())

    def test_start_execution_rejects_revision_mismatch_without_update(self) -> None:
        self.initialize()
        self.approve()
        content = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(content.replace("revision: 1", "revision: 2", 1), encoding="utf-8")
        original = self.plan.read_bytes()
        result = self.run_command(
            "start-execution",
            str(self.plan),
            "--confirmation",
            "I approve test-plan revision 1.",
            expected=2,
        )
        self.assertIn("does not match revision 2", result.stderr)
        self.assertEqual(original, self.plan.read_bytes())

    def test_complete_requires_in_progress_and_current_approval(self) -> None:
        self.initialize()
        result = self.run_command("complete", str(self.plan), expected=2)
        self.assertIn("requires IN_PROGRESS", result.stderr)

        self.start_execution()
        self.run_command("complete", str(self.plan))
        self.assertEqual("COMPLETED", self.inspect()["phase"])
        result = self.run_command("complete", str(self.plan), expected=2)
        self.assertIn("requires IN_PROGRESS", result.stderr)

    def test_complete_rejects_missing_or_incomplete_orchestration_atomically(self) -> None:
        """Do not complete when companion scheduler evidence is unavailable or unfinished."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            str(repo),
            "--vcs-mode",
            "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'execution_mode: "SINGLE_AGENT"',
            'agent_topology: "SHARED_WORKSPACE"',
            'orchestration_state: ".codex/project-workflow/test-plan/orchestration.json"',
            'filesystem_snapshot_scopes: []',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        self.approve()
        approved_plan = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            approved_plan.replace(
                'filesystem_write_scopes: ["module-a"]',
                'filesystem_write_scopes: ["module-a","module-b"]',
            ),
            encoding="utf-8",
        )
        drifted = self.run_command(
            "create-baseline", str(self.plan), "--repo", str(repo),
            "--write-scope", "module-a",
            expected=2,
        )
        self.assertIn("approved filesystem policy", drifted.stderr)
        self.plan.write_text(approved_plan, encoding="utf-8")
        self.run_command(
            "create-baseline", str(self.plan), "--repo", str(repo),
            "--write-scope", "module-a",
        )
        self.run_command(
            "start-execution",
            str(self.plan),
            "--repo",
            str(repo),
            "--confirmation",
            "I approve test-plan revision 1.",
        )
        before = self.plan.read_bytes()
        missing = self.run_command(
            "complete", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("does not exist", missing.stderr)
        self.assertEqual(before, self.plan.read_bytes())

        self.write_orchestration_state(completed=False)
        incomplete = self.run_command(
            "complete", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("completed tasks", incomplete.stderr)
        self.assertEqual(before, self.plan.read_bytes())

    def test_complete_binds_validated_orchestration_version(self) -> None:
        """Persist the exact scheduler version accepted by the final gate."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            str(repo),
            "--vcs-mode",
            "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'execution_mode: "SINGLE_AGENT"',
            'agent_topology: "SHARED_WORKSPACE"',
            'orchestration_state: ".codex/project-workflow/test-plan/orchestration.json"',
            'filesystem_snapshot_scopes: ["module-a"]',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        module = repo / "module-a"
        module.mkdir()
        tracked = module / "value.txt"
        tracked.write_text("before", encoding="utf-8")
        self.approve()
        self.run_command(
            "create-baseline", str(self.plan), "--repo", str(repo),
            "--scope", "module-a", "--write-scope", "module-a",
        )
        self.run_command(
            "start-execution",
            str(self.plan),
            "--repo",
            str(repo),
            "--confirmation",
            "I approve test-plan revision 1.",
        )
        tracked.write_text("after", encoding="utf-8")
        self.write_orchestration_state(completed=True)
        self.run_command("complete", str(self.plan), "--repo", str(repo))
        metadata = self.inspect()
        self.assertEqual("COMPLETED", metadata["phase"])
        self.assertEqual(7, metadata["final_orchestration_state_version"])
        self.assertEqual(1, metadata["final_filesystem_modified_count"])
        self.assertEqual(64, len(metadata["final_filesystem_evidence_sha256"]))

    def test_current_none_single_agent_requires_clean_final_scope_evidence(self) -> None:
        """Bind a recomputed baseline comparison for current serial NONE plans."""
        repo = Path(self.temporary_directory.name)
        module = repo / "module-a"
        module.mkdir()
        tracked = module / "value.txt"
        tracked.write_text("before", encoding="utf-8")
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            str(repo),
            "--vcs-mode",
            "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            'execution_mode: "SINGLE_AGENT"',
            'agent_topology: "SHARED_WORKSPACE"',
            'filesystem_snapshot_scopes: ["module-a","module-b"]',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        self.approve()
        self.run_command(
            "create-baseline", str(self.plan), "--repo", str(repo),
            "--scope", "module-a", "--scope", "module-b",
            "--write-scope", "module-a",
        )
        self.run_command(
            "start-execution",
            str(self.plan),
            "--repo",
            str(repo),
            "--confirmation",
            "I approve test-plan revision 1.",
        )
        tracked.write_text("after", encoding="utf-8")
        outside = repo / "module-b"
        outside.mkdir()
        (outside / "escape.txt").write_text("outside", encoding="utf-8")
        before = self.plan.read_bytes()
        rejected = self.run_command(
            "complete", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("out-of-scope", rejected.stderr)
        self.assertEqual(before, self.plan.read_bytes())

        (outside / "escape.txt").unlink()
        outside.rmdir()
        self.run_command("complete", str(self.plan), "--repo", str(repo))
        metadata = self.inspect()
        self.assertEqual("COMPLETED", metadata["phase"])
        self.assertEqual(1, metadata["final_filesystem_modified_count"])

    def test_current_none_baseline_is_approval_bound_and_completion_is_recheckable(self) -> None:
        """Persist immutable approval-bound baseline and final artifacts for later validation."""
        repo = Path(self.temporary_directory.name)
        module = repo / "module-a"
        module.mkdir()
        tracked = module / "value.txt"
        tracked.write_text("before", encoding="utf-8")
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--repo", str(repo),
            "--vcs-mode", "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            'execution_mode: "SINGLE_AGENT"',
            'agent_topology: "SHARED_WORKSPACE"',
            'filesystem_snapshot_scopes: ["module-a"]',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        self.approve()
        self.run_command(
            "create-baseline", str(self.plan), "--repo", str(repo),
            "--scope", "module-a", "--write-scope", "module-a",
        )
        bound = self.inspect()
        self.assertEqual(64, len(bound["filesystem_baseline_sha256"]))
        baseline = json.loads(
            (repo / str(bound["filesystem_baseline"])).read_text(encoding="utf-8")
        )
        self.assertEqual("test-plan", baseline["binding"]["plan_id"])
        self.assertEqual(1, baseline["binding"]["approved_revision"])
        self.assertEqual(64, len(baseline["binding"]["confirmation_sha256"]))

        self.run_command(
            "start-execution", str(self.plan), "--repo", str(repo),
            "--confirmation", "I approve test-plan revision 1.",
        )
        tracked.write_text("after", encoding="utf-8")
        self.run_command("complete", str(self.plan), "--repo", str(repo))
        completed = self.inspect()
        artifact_path = repo / str(completed["final_filesystem_artifact"])
        baseline_path = repo / str(completed["filesystem_baseline"])
        self.assertTrue(artifact_path.is_file())
        self.assertEqual(64, len(completed["final_filesystem_artifact_sha256"]))
        self.run_command("validate", str(self.plan), "--repo", str(repo))

        baseline_bytes = baseline_path.read_bytes()
        baseline_path.unlink()
        missing = self.run_command(
            "validate", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("filesystem JSON", missing.stderr)
        baseline_path.write_bytes(baseline_bytes)

        valid_plan = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            valid_plan.replace(
                "final_filesystem_modified_count: 1",
                "final_filesystem_modified_count: 999",
            ),
            encoding="utf-8",
        )
        invalid_count = self.run_command(
            "validate", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("count does not match", invalid_count.stderr)
        self.plan.write_text(valid_plan, encoding="utf-8")

        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["modified"] = []
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
        rejected = self.run_command(
            "validate", str(self.plan), "--repo", str(repo), expected=2
        )
        self.assertIn("final filesystem artifact", rejected.stderr)

    def test_current_none_canonical_start_creates_bound_baseline(self) -> None:
        """The canonical confirmation path creates evidence before entering execution."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--repo", str(repo),
            "--vcs-mode", "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            'agent_topology: "SHARED_WORKSPACE"',
            'filesystem_snapshot_scopes: []',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        self.run_command(
            "start-execution", str(self.plan), "--repo", str(repo),
            "--confirmation", "I approve test-plan revision 1.",
            "--at", "2026-08-20T00:00:00+00:00",
        )
        metadata = self.inspect()
        self.assertEqual("IN_PROGRESS", metadata["phase"])
        baseline_path = repo / str(metadata["filesystem_baseline"])
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.assertEqual("test-plan", baseline["binding"]["plan_id"])
        self.assertEqual(
            hashlib.sha256(b"I approve test-plan revision 1.").hexdigest(),
            baseline["binding"]["confirmation_sha256"],
        )

    def test_current_none_canonical_start_rejects_conflicting_baseline_atomically(self) -> None:
        """A pre-existing different baseline cannot reset approval or plan phase."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--repo", str(repo),
            "--vcs-mode", "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            'agent_topology: "SHARED_WORKSPACE"',
            'filesystem_snapshot_scopes: []',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        self.create_none_baseline()
        baseline_path = (
            repo / ".codex/project-workflow/test-plan/filesystem-baseline.json"
        )
        baseline_before = baseline_path.read_bytes()
        plan_before = self.plan.read_bytes()
        conflict = self.run_command(
            "start-execution", str(self.plan), "--repo", str(repo),
            "--confirmation", "I approve test-plan revision 1.", expected=2,
        )
        self.assertIn("already exists", conflict.stderr)
        self.assertEqual(plan_before, self.plan.read_bytes())
        self.assertEqual(baseline_before, baseline_path.read_bytes())

    def test_current_none_start_write_failure_is_retryable_without_false_success(self) -> None:
        """An orphaned exact baseline is reusable after the plan replacement fails."""
        repo = Path(self.temporary_directory.name)
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--repo", str(repo),
            "--vcs-mode", "NONE",
        )
        self.add_metadata(
            'workflow_profile: "LIGHT"',
            'rollback_required: "false"',
            'agent_topology: "SHARED_WORKSPACE"',
            'filesystem_snapshot_scopes: []',
            'filesystem_snapshot_excludes: []',
            'filesystem_write_scopes: ["module-a"]',
        )
        plan_before = self.plan.read_bytes()
        scripts = str(SCRIPT.parent)
        sys.path.insert(0, scripts)
        self.addCleanup(lambda: sys.path.remove(scripts))
        spec = importlib.util.spec_from_file_location("workflow_state_retry", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = module.build_parser().parse_args(
            [
                "start-execution", str(self.plan), "--repo", str(repo),
                "--confirmation", "I approve test-plan revision 1.",
                "--at", "2026-08-20T00:00:00+00:00",
            ]
        )
        module.normalize_command_paths(args)
        with mock.patch.object(module, "write_document", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                with module.locked_plan(args.plan):
                    module.command_start_execution(args)
        self.assertEqual(plan_before, self.plan.read_bytes())
        self.assertTrue(
            (repo / ".codex/project-workflow/test-plan/filesystem-baseline.json").is_file()
        )

        self.run_command(
            "start-execution", str(self.plan), "--repo", str(repo),
            "--confirmation", "I approve test-plan revision 1.",
            "--at", "2026-08-20T00:00:00+00:00",
        )
        self.assertEqual("IN_PROGRESS", self.inspect()["phase"])

    def test_pure_v03_plan_remains_legacy_compatible(self) -> None:
        """Only plans without every v0.4 marker retain the historical NONE bypass."""
        self.plan.write_text(
            """---
workflow: "project-workflow/v1"
plan_id: "legacy"
revision: 1
phase: "IN_PROGRESS"
approved_revision: 1
approved_at: "2026-08-20T00:00:00+00:00"
confirmation_record: "legacy approval"
---

# Legacy v0.3 plan
""",
            encoding="utf-8",
        )
        initialized = subprocess.run(
            ["git", "init", self.temporary_directory.name],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        self.run_command("validate", str(self.plan), "--repo", self.temporary_directory.name)
        self.assertEqual("IN_PROGRESS", self.inspect()["phase"])

    def test_explicit_repo_rejects_plan_escape_without_mutation(self) -> None:
        """Keep repository-relative lifecycle paths inside the supplied repository."""
        repo = Path(self.temporary_directory.name) / "repo"
        repo.mkdir()
        outside = Path(self.temporary_directory.name) / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        before = outside.read_bytes()
        result = self.run_command(
            "init",
            str(outside),
            "--plan-id",
            "outside",
            "--repo",
            str(repo),
            expected=2,
        )
        self.assertIn("inside repository", result.stderr)
        self.assertEqual(before, outside.read_bytes())

    def test_validate_rejects_boolean_like_revision(self) -> None:
        self.initialize()
        content = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(content.replace("revision: 1", "revision: true", 1), encoding="utf-8")
        result = self.run_command("validate", str(self.plan), expected=2)
        self.assertIn("revision must be a positive integer", result.stderr)

    def test_init_resolves_auto_to_none_in_plain_directory(self) -> None:
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            self.temporary_directory.name,
        )
        metadata = self.inspect()
        self.assertEqual("AUTO", metadata["vcs_mode"])
        self.assertEqual("NONE", metadata["resolved_vcs_mode"])

    def test_explicit_git_failure_does_not_partially_initialize(self) -> None:
        original = self.plan.read_bytes()
        result = self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            self.temporary_directory.name,
            "--vcs-mode",
            "GIT",
            expected=2,
        )
        self.assertIn("requires executable Git", result.stderr)
        self.assertEqual(original, self.plan.read_bytes())

    def test_full_none_requires_three_verified_rollback_fields(self) -> None:
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            self.temporary_directory.name,
            "--vcs-mode",
            "NONE",
        )
        content = self.plan.read_text(encoding="utf-8")
        content = content.replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "FULL"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        result = self.run_command(
            "check-execute",
            str(self.plan),
            "--repo",
            self.temporary_directory.name,
            expected=2,
        )
        self.assertIn("verified equivalent rollback evidence", result.stderr)

        content = self.plan.read_text(encoding="utf-8")
        content = content.replace(
            'workflow_profile: "FULL"\n',
            'workflow_profile: "FULL"\n'
            'rollback_strategy: "restore snapshot"\n'
            'rollback_evidence: "snapshot restore tested"\n'
            'rollback_verification: "VERIFIED"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.run_command(
            "check-execute",
            str(self.plan),
            "--repo",
            self.temporary_directory.name,
        )

    def test_auto_environment_drift_blocks_execution(self) -> None:
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            self.temporary_directory.name,
        )
        content = self.plan.read_text(encoding="utf-8")
        content = content.replace('resolved_vcs_mode: "NONE"', 'resolved_vcs_mode: "GIT"')
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        result = self.run_command(
            "check-execute",
            str(self.plan),
            "--repo",
            self.temporary_directory.name,
            expected=2,
        )
        self.assertIn("environment drift", result.stderr)

    def test_light_legacy_plan_without_vcs_fields_can_execute_without_git(self) -> None:
        self.initialize()
        content = self.plan.read_text(encoding="utf-8")
        content = "\n".join(
            line
            for line in content.splitlines()
            if not line.startswith("vcs_mode:") and not line.startswith("resolved_vcs_mode:")
        ) + "\n"
        content = content.replace(
            'progress_heartbeat_minutes: 5\n',
            'progress_heartbeat_minutes: 5\nworkflow_profile: "LIGHT"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        self.run_command(
            "check-execute",
            str(self.plan),
            "--repo",
            self.temporary_directory.name,
        )

    def test_unknown_rollback_verification_is_rejected(self) -> None:
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--repo",
            self.temporary_directory.name,
            "--vcs-mode",
            "NONE",
        )
        content = self.plan.read_text(encoding="utf-8")
        content = content.replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "LIGHT"\n'
            'rollback_verification: "YES"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        result = self.run_command(
            "check-execute",
            str(self.plan),
            "--repo",
            self.temporary_directory.name,
            expected=2,
        )
        self.assertIn("must be VERIFIED", result.stderr)

    def test_blocked_plan_requires_resume_gate(self) -> None:
        """Prevent low-level transition from bypassing approval and VCS checks."""
        self.initialize()
        self.approve()
        self.run_command("transition", str(self.plan), "IN_PROGRESS")
        self.run_command("transition", str(self.plan), "BLOCKED")
        failure = self.run_command(
            "transition", str(self.plan), "IN_PROGRESS", expected=2
        )
        self.assertIn("illegal transition", failure.stderr)
        self.run_command("resume", str(self.plan))
        self.assertEqual("IN_PROGRESS", self.inspect()["phase"])

    def test_resume_replays_revision_and_vcs_gates(self) -> None:
        """Reject recovery when approval or the approved evidence model drifted."""
        self.initialize()
        self.approve()
        self.run_command("transition", str(self.plan), "IN_PROGRESS")
        self.run_command("transition", str(self.plan), "BLOCKED")
        original = self.plan.read_text(encoding="utf-8")
        self.plan.write_text(
            original.replace("approved_revision: 1", "approved_revision: 2"),
            encoding="utf-8",
        )
        failure = self.run_command("resume", str(self.plan), expected=2)
        self.assertIn("does not match revision", failure.stderr)
        self.plan.write_text(
            original.replace('resolved_vcs_mode: "GIT"', 'resolved_vcs_mode: "NONE"'),
            encoding="utf-8",
        )
        failure = self.run_command("resume", str(self.plan), expected=2)
        self.assertIn("environment drift", failure.stderr)

    def test_rollback_required_is_strict_and_enforced_for_light_none(self) -> None:
        """Require verified recovery for an explicit rollback requirement in NONE."""
        self.run_command(
            "init",
            str(self.plan),
            "--plan-id",
            "test-plan",
            "--vcs-mode",
            "NONE",
        )
        content = self.plan.read_text(encoding="utf-8").replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "LIGHT"\n'
            'rollback_required: "true"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        failure = self.run_command("check-execute", str(self.plan), expected=2)
        self.assertIn("verified equivalent rollback evidence", failure.stderr)

        content = self.plan.read_text(encoding="utf-8").replace(
            'rollback_required: "true"', 'rollback_required: "yes"'
        )
        self.plan.write_text(content, encoding="utf-8")
        failure = self.run_command("check-execute", str(self.plan), expected=2)
        self.assertIn("must be the string true or false", failure.stderr)

    def test_none_rejects_non_shared_topology(self) -> None:
        """Keep NONE execution on its only supported workspace topology."""
        self.run_command(
            "init", str(self.plan), "--plan-id", "test-plan", "--vcs-mode", "NONE"
        )
        content = self.plan.read_text(encoding="utf-8").replace(
            'resolved_vcs_mode: "NONE"\n',
            'resolved_vcs_mode: "NONE"\nworkflow_profile: "LIGHT"\n'
            'agent_topology: "ISOLATED_WORKTREE"\n',
        )
        self.plan.write_text(content, encoding="utf-8")
        self.approve()
        failure = self.run_command("check-execute", str(self.plan), expected=2)
        self.assertIn("requires SHARED_WORKSPACE", failure.stderr)

    def test_repo_dot_is_resolved_from_process_cwd(self) -> None:
        """Keep conventional CLI semantics for an explicit relative repository."""
        result = subprocess.run(
            ["git", "init", str(self.plan.parent)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        command = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "init",
                str(self.plan),
                "--plan-id",
                "test-plan",
                "--repo",
                ".",
            ],
            cwd=self.plan.parent,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, command.returncode, command.stderr)
        self.assertEqual("GIT", self.inspect()["resolved_vcs_mode"])

    def test_relative_plan_is_resolved_from_explicit_absolute_repo(self) -> None:
        """Allow callers outside a repository to address its plan repo-relatively."""
        repository = Path(self.temporary_directory.name) / "repository"
        repository.mkdir()
        result = subprocess.run(
            ["git", "init", str(repository)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        relative_plan = repository / "docs" / "plan.md"
        relative_plan.parent.mkdir()
        relative_plan.write_text("# Relative Plan\n", encoding="utf-8")
        outside = Path(self.temporary_directory.name) / "caller"
        outside.mkdir()
        command = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "init",
                "docs/plan.md",
                "--plan-id",
                "relative-plan",
                "--repo",
                str(repository),
            ],
            cwd=outside,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, command.returncode, command.stderr)
        inspected = subprocess.run(
            [sys.executable, str(SCRIPT), "inspect", str(relative_plan)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, inspected.returncode, inspected.stderr)
        self.assertEqual("GIT", json.loads(inspected.stdout)["resolved_vcs_mode"])


if __name__ == "__main__":
    unittest.main()
